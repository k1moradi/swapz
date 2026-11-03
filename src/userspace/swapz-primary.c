// SPDX-License-Identifier: GPL-2.0-only
#define _GNU_SOURCE
#include "swapz-primary.h"

#include <ctype.h>
#include <dirent.h>
#include <errno.h>
#include <fcntl.h>
#include <limits.h>
#include <linux/fs.h>
#include <linux/magic.h>
#include <stdarg.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/ioctl.h>
#include <sys/file.h>
#include <sys/mman.h>
#include <sys/stat.h>
#include <sys/sysmacros.h>
#include <sys/types.h>
#include <sys/vfs.h>
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
#define SWAPZ_PRIMARY_MOUNTINFO_BUFFER_BYTES 65536U
#define SWAPZ_PRIMARY_DM_MAPPERS_MAX 512U
#define SWAPZ_PRIMARY_SWAP_ROWS_MAX 32U
#define SWAPZ_PRIMARY_STATE_RECORD_MAX 4096U
#define SWAPZ_PRIMARY_STATE_JSON_PREFIX \
	"{\"schema\":\"swapz-primary-state-v1\",\"run_id\":"
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

static const char *const swapz_primary_stage_names[] = {
	[SWAPZ_PRIMARY_STAGE_READY] = "READY",
	[SWAPZ_PRIMARY_STAGE_STARTING] = "STARTING",
	[SWAPZ_PRIMARY_STAGE_ACTIVE] = "ACTIVE",
	[SWAPZ_PRIMARY_STAGE_STOPPING] = "STOPPING",
	[SWAPZ_PRIMARY_STAGE_RECOVERING] = "RECOVERING",
	[SWAPZ_PRIMARY_STAGE_RESTORED] = "RESTORED",
	[SWAPZ_PRIMARY_STAGE_DISABLING] = "DISABLING",
	[SWAPZ_PRIMARY_STAGE_COMPLETE] = "COMPLETE",
	[SWAPZ_PRIMARY_STAGE_RECOVERY_REQUIRED] = "RECOVERY_REQUIRED",
};

static int swapz_primary_valid_run_id(const char *run_id);

const char *swapz_primary_stage_name(enum swapz_primary_stage stage)
{
	if ((unsigned int)stage >= (unsigned int)SWAPZ_PRIMARY_STAGE_COUNT)
		return NULL;
	return swapz_primary_stage_names[stage];
}

int swapz_primary_stage_parse(const char *name,
			      enum swapz_primary_stage *stage)
{
	enum swapz_primary_stage candidate;

	if (!name || !stage)
		return -1;
	for (candidate = SWAPZ_PRIMARY_STAGE_READY;
	     (unsigned int)candidate < (unsigned int)SWAPZ_PRIMARY_STAGE_COUNT;
	     ++candidate) {
		if (!strcmp(name, swapz_primary_stage_names[candidate])) {
			*stage = candidate;
			return 0;
		}
	}
	return -1;
}

int swapz_primary_stage_transition_allowed(enum swapz_primary_stage from,
						   enum swapz_primary_stage to)
{
	if ((unsigned int)from >= (unsigned int)SWAPZ_PRIMARY_STAGE_COUNT ||
	    (unsigned int)to >= (unsigned int)SWAPZ_PRIMARY_STAGE_COUNT)
		return 0;
	if (from == to)
		return from != SWAPZ_PRIMARY_STAGE_COMPLETE;
	if (to == SWAPZ_PRIMARY_STAGE_RECOVERY_REQUIRED)
		return from != SWAPZ_PRIMARY_STAGE_COMPLETE;
	switch (from) {
	case SWAPZ_PRIMARY_STAGE_READY:
		return to == SWAPZ_PRIMARY_STAGE_STARTING ||
		       to == SWAPZ_PRIMARY_STAGE_DISABLING;
	case SWAPZ_PRIMARY_STAGE_STARTING:
		return to == SWAPZ_PRIMARY_STAGE_ACTIVE;
	case SWAPZ_PRIMARY_STAGE_ACTIVE:
		return to == SWAPZ_PRIMARY_STAGE_STOPPING;
	case SWAPZ_PRIMARY_STAGE_STOPPING:
		return to == SWAPZ_PRIMARY_STAGE_RESTORED;
	case SWAPZ_PRIMARY_STAGE_RECOVERING:
		return to == SWAPZ_PRIMARY_STAGE_RESTORED;
	case SWAPZ_PRIMARY_STAGE_RESTORED:
		return to == SWAPZ_PRIMARY_STAGE_COMPLETE;
	case SWAPZ_PRIMARY_STAGE_DISABLING:
		return to == SWAPZ_PRIMARY_STAGE_COMPLETE;
	case SWAPZ_PRIMARY_STAGE_RECOVERY_REQUIRED:
		return to == SWAPZ_PRIMARY_STAGE_RECOVERING;
	case SWAPZ_PRIMARY_STAGE_COMPLETE:
	case SWAPZ_PRIMARY_STAGE_COUNT:
		return 0;
	}
	return 0;
}

static int swapz_primary_state_string(const char **cursor,
				      const char *end, char *value,
				      size_t capacity)
{
	size_t length = 0;

	if (!cursor || !*cursor || !value || !capacity || *cursor >= end ||
	    **cursor != '"')
		return -1;
	++*cursor;
	while (*cursor < end && **cursor != '"') {
		unsigned char byte = (unsigned char)**cursor;

		if (byte < 0x20U || byte > 0x7eU || byte == '\\' ||
		    length + 1U >= capacity)
			return -1;
		value[length++] = (char)byte;
		++*cursor;
	}
	if (*cursor >= end || **cursor != '"')
		return -1;
	++*cursor;
	value[length] = '\0';
	return 0;
}

static int swapz_primary_state_run_id_valid(const char *run_id)
{
	unsigned int i;

	if (!run_id || run_id[SWAPZ_PRIMARY_RUN_ID_LENGTH] != '\0')
		return 0;
	for (i = 0; i < SWAPZ_PRIMARY_RUN_ID_LENGTH; ++i)
		if (!((run_id[i] >= '0' && run_id[i] <= '9') ||
		      (run_id[i] >= 'a' && run_id[i] <= 'f')))
			return 0;
	return 1;
}

static int swapz_primary_state_valid(const struct swapz_primary_state *state)
{
	if (!state || !swapz_primary_state_run_id_valid(state->run_id) ||
	    (state->has_recovery_previous_stage != 0 &&
	     state->has_recovery_previous_stage != 1) ||
	    (unsigned int)state->stage >=
			(unsigned int)SWAPZ_PRIMARY_STAGE_COUNT)
		return 0;
	if (!state->has_recovery_previous_stage)
		return state->stage != SWAPZ_PRIMARY_STAGE_RECOVERY_REQUIRED &&
		       state->stage != SWAPZ_PRIMARY_STAGE_RECOVERING;
	if ((unsigned int)state->recovery_previous_stage >=
	    (unsigned int)SWAPZ_PRIMARY_STAGE_COUNT ||
	    state->recovery_previous_stage == SWAPZ_PRIMARY_STAGE_COMPLETE ||
	    state->recovery_previous_stage ==
			SWAPZ_PRIMARY_STAGE_RECOVERY_REQUIRED ||
	    state->recovery_previous_stage == SWAPZ_PRIMARY_STAGE_RECOVERING)
		return 0;
	return state->stage == SWAPZ_PRIMARY_STAGE_RECOVERY_REQUIRED ||
	       state->stage == SWAPZ_PRIMARY_STAGE_RECOVERING ||
	       state->stage == SWAPZ_PRIMARY_STAGE_RESTORED ||
	       state->stage == SWAPZ_PRIMARY_STAGE_COMPLETE;
}

int swapz_primary_state_parse(const char *record, size_t length,
			      struct swapz_primary_state *state)
{
	struct swapz_primary_state parsed = {0};
	char token[64];
	const char *cursor;
	const char *end;

	if (!record || !state || !length ||
	    length > SWAPZ_PRIMARY_STATE_RECORD_MAX ||
	    memchr(record, '\0', length))
		return -1;
	cursor = record;
	end = record + length;
	if ((size_t)(end - cursor) < sizeof(SWAPZ_PRIMARY_STATE_JSON_PREFIX) - 1U ||
	    memcmp(cursor, SWAPZ_PRIMARY_STATE_JSON_PREFIX,
		   sizeof(SWAPZ_PRIMARY_STATE_JSON_PREFIX) - 1U))
		return -1;
	cursor += sizeof(SWAPZ_PRIMARY_STATE_JSON_PREFIX) - 1U;
	if (swapz_primary_state_string(&cursor, end, parsed.run_id,
				       sizeof(parsed.run_id)) < 0 ||
	    !swapz_primary_valid_run_id(parsed.run_id) ||
	    (size_t)(end - cursor) < sizeof(",\"stage\":") - 1U ||
	    memcmp(cursor, ",\"stage\":", sizeof(",\"stage\":") - 1U))
		return -1;
	cursor += sizeof(",\"stage\":") - 1U;
	if (swapz_primary_state_string(&cursor, end, token, sizeof(token)) < 0 ||
	    swapz_primary_stage_parse(token, &parsed.stage) < 0 ||
	    (size_t)(end - cursor) <
		    sizeof(",\"recovery_previous_stage\":") - 1U ||
	    memcmp(cursor, ",\"recovery_previous_stage\":",
		   sizeof(",\"recovery_previous_stage\":") - 1U))
		return -1;
	cursor += sizeof(",\"recovery_previous_stage\":") - 1U;
	if ((size_t)(end - cursor) >= sizeof("null}\n") - 1U &&
	    !memcmp(cursor, "null}\n", sizeof("null}\n") - 1U)) {
		cursor += sizeof("null}\n") - 1U;
	} else {
		if (swapz_primary_state_string(&cursor, end, token,
					       sizeof(token)) < 0 ||
		    swapz_primary_stage_parse(token,
					     &parsed.recovery_previous_stage) < 0 ||
		    (size_t)(end - cursor) < sizeof("}\n") - 1U ||
		    memcmp(cursor, "}\n", sizeof("}\n") - 1U))
			return -1;
		cursor += sizeof("}\n") - 1U;
		parsed.has_recovery_previous_stage = 1;
	}
	if (cursor != end || !swapz_primary_state_valid(&parsed))
		return -1;
	*state = parsed;
	return 0;
}

int swapz_primary_state_format(const struct swapz_primary_state *state,
			       char *record, size_t capacity)
{
	const char *previous = "null";
	int length;

	if (!swapz_primary_state_valid(state) || !record || !capacity) {
		errno = EINVAL;
		return -1;
	}
	if (state->has_recovery_previous_stage)
		previous = swapz_primary_stage_name(
			state->recovery_previous_stage);
	length = snprintf(record, capacity,
			  SWAPZ_PRIMARY_STATE_JSON_PREFIX
			  "\"%s\",\"stage\":\"%s\","
			  "\"recovery_previous_stage\":%s%s%s}\n",
			  state->run_id, swapz_primary_stage_name(state->stage),
			  state->has_recovery_previous_stage ? "\"" : "",
			  previous,
			  state->has_recovery_previous_stage ? "\"" : "");
	if (length < 0 || (size_t)length >= capacity ||
	    (size_t)length > SWAPZ_PRIMARY_STATE_RECORD_MAX) {
		errno = EOVERFLOW;
		return -1;
	}
	return length;
}

int swapz_primary_state_transition_allowed(
	const struct swapz_primary_state *current,
	const struct swapz_primary_state *next)
{
	enum swapz_primary_stage recovery_origin;

	if (!swapz_primary_state_valid(current) ||
	    !swapz_primary_state_valid(next))
		return 0;
	if (strcmp(current->run_id, next->run_id))
		return current->stage == SWAPZ_PRIMARY_STAGE_COMPLETE &&
		       next->stage == SWAPZ_PRIMARY_STAGE_READY &&
		       !next->has_recovery_previous_stage;
	if (current->stage == SWAPZ_PRIMARY_STAGE_COMPLETE)
		return 0;
	if (next->stage == SWAPZ_PRIMARY_STAGE_RECOVERY_REQUIRED) {
		recovery_origin = current->has_recovery_previous_stage ?
			current->recovery_previous_stage : current->stage;
		return next->has_recovery_previous_stage &&
		       next->recovery_previous_stage == recovery_origin;
	}
	if (current->stage == SWAPZ_PRIMARY_STAGE_RECOVERY_REQUIRED ||
	    current->stage == SWAPZ_PRIMARY_STAGE_RECOVERING) {
		if (!current->has_recovery_previous_stage ||
		    !next->has_recovery_previous_stage ||
		    current->recovery_previous_stage !=
			    next->recovery_previous_stage)
			return 0;
	} else if (current->stage == SWAPZ_PRIMARY_STAGE_RESTORED &&
		   current->has_recovery_previous_stage) {
		if (!next->has_recovery_previous_stage ||
		    current->recovery_previous_stage !=
			    next->recovery_previous_stage)
			return 0;
	} else if (current->has_recovery_previous_stage ||
		   next->has_recovery_previous_stage) {
		return 0;
	}
	return swapz_primary_stage_transition_allowed(current->stage,
						      next->stage);
}

static int swapz_primary_device_number_matches(dev_t device)
{
	return major(device) == 8U && minor(device) == 4U;
}

static int swapz_primary_same_target_identity(const struct stat *left,
					     const struct stat *right)
{
	if (!left || !right)
		return 0;
#ifdef SWAPZ_PRIMARY_ROOTLESS_TEST
	return S_ISREG(left->st_mode) && S_ISREG(right->st_mode) &&
	       left->st_dev == right->st_dev && left->st_ino == right->st_ino;
#else
	return S_ISBLK(left->st_mode) && S_ISBLK(right->st_mode) &&
	       swapz_primary_device_number_matches(left->st_rdev) &&
	       left->st_rdev == right->st_rdev;
#endif
}

static int swapz_primary_open_target_checked_paths(const char *device_path,
						   const char *uuid_path,
						   const char *partuuid_path)
{
	struct stat device_before;
	struct stat uuid_before;
	struct stat partuuid_before;
	struct stat opened;
	struct stat device_after;
	struct stat uuid_after;
	struct stat partuuid_after;
	int fd;

	if (!device_path || !uuid_path || !partuuid_path) {
		errno = EINVAL;
		return -1;
	}
	if (stat(device_path, &device_before) < 0 ||
	    stat(uuid_path, &uuid_before) < 0 ||
	    stat(partuuid_path, &partuuid_before) < 0)
		return -1;
	if (!swapz_primary_same_target_identity(&device_before, &uuid_before) ||
	    !swapz_primary_same_target_identity(&uuid_before, &partuuid_before)) {
		errno = ENODEV;
		return -1;
	}
	fd = open(uuid_path, O_RDWR | O_EXCL | O_NONBLOCK | O_CLOEXEC);
	if (fd < 0)
		return -1;
	if (fstat(fd, &opened) < 0)
		goto failed;
	if (!swapz_primary_same_target_identity(&uuid_before, &opened) ||
	    stat(device_path, &device_after) < 0 ||
	    stat(uuid_path, &uuid_after) < 0 ||
	    stat(partuuid_path, &partuuid_after) < 0 ||
	    !swapz_primary_same_target_identity(&opened, &device_after) ||
	    !swapz_primary_same_target_identity(&opened, &uuid_after) ||
	    !swapz_primary_same_target_identity(&opened, &partuuid_after)) {
		errno = ENODEV;
		goto failed;
	}
#ifdef SWAPZ_PRIMARY_ROOTLESS_TEST
	if (opened.st_size < (off_t)SWAPZ_PRIMARY_BLOCK_BYTES) {
		errno = EINVAL;
		goto failed;
	}
#else
	{
		uint64_t bytes = 0;

		if (ioctl(fd, BLKGETSIZE64, &bytes) < 0)
			goto failed;
		if (bytes != SWAPZ_PRIMARY_DEVICE_BYTES) {
			errno = EINVAL;
			goto failed;
		}
	}
#endif
	return fd;

failed:
	{
		int saved_errno = errno;

		close(fd);
		errno = saved_errno;
	}
	return -1;
}

int swapz_primary_target_open_exclusive(void)
{
#ifdef SWAPZ_PRIMARY_ROOTLESS_TEST
	errno = ENOTSUP;
	return -1;
#else
	return swapz_primary_open_target_checked_paths(
		SWAPZ_PRIMARY_DEVICE_PATH, SWAPZ_PRIMARY_UUID_PATH,
		SWAPZ_PRIMARY_PARTUUID_PATH);
#endif
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

static int swapz_primary_header_fd_valid(int fd)
{
	struct stat info;
	int flags;

	if (fd < 0 || fstat(fd, &info) < 0)
		return 0;
	flags = fcntl(fd, F_GETFL);
	if (flags < 0)
		return 0;
	if ((flags & O_ACCMODE) != O_RDWR) {
		errno = EBADF;
		return 0;
	}
#ifdef SWAPZ_PRIMARY_ROOTLESS_TEST
	if (!S_ISREG(info.st_mode) ||
	    info.st_size < (off_t)SWAPZ_PRIMARY_BLOCK_BYTES) {
		errno = ENODEV;
		return 0;
	}
#else
	{
		uint64_t bytes = 0;

		if (!S_ISBLK(info.st_mode) ||
		    !swapz_primary_device_number_matches(info.st_rdev)) {
			errno = EPERM;
			return 0;
		}
		if (ioctl(fd, BLKGETSIZE64, &bytes) < 0)
			return 0;
		if (bytes != SWAPZ_PRIMARY_DEVICE_BYTES) {
			errno = EINVAL;
			return 0;
		}
	}
#endif
	return 1;
}

int swapz_primary_write_header_checked_fd(
	int fd, const unsigned char expected_current[SWAPZ_PRIMARY_BLOCK_BYTES],
	const unsigned char replacement[SWAPZ_PRIMARY_BLOCK_BYTES])
{
	unsigned char observed[SWAPZ_PRIMARY_BLOCK_BYTES];
	size_t completed = 0;

	if (!expected_current || !replacement) {
		errno = EINVAL;
		return -1;
	}
	if (!swapz_primary_header_fd_valid(fd))
		return -1;
	if (swapz_primary_exact_read(fd, observed, sizeof(observed)) < 0)
		return -1;
	if (memcmp(observed, expected_current, sizeof(observed))) {
		errno = ESTALE;
		return -1;
	}
	while (completed < sizeof(observed)) {
		ssize_t count = pwrite(fd, replacement + completed,
				       sizeof(observed) - completed,
				       (off_t)completed);

		if (count < 0 && errno == EINTR)
			continue;
		if (count <= 0) {
			if (!count)
				errno = EIO;
			return -1;
		}
		completed += (size_t)count;
	}
	if (fsync(fd) < 0 || !swapz_primary_header_fd_valid(fd) ||
	    swapz_primary_exact_read(fd, observed, sizeof(observed)) < 0)
		return -1;
	if (memcmp(observed, replacement, sizeof(observed))) {
		errno = EIO;
		return -1;
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

static int swapz_primary_parse_dev_number(const char *text, dev_t *device)
{
	const char *colon;
	char major_text[32];
	uint64_t major_number;
	uint64_t minor_number;
	size_t major_length;

	if (!text || !device) {
		errno = EINVAL;
		return -1;
	}
	colon = strchr(text, ':');
	if (!colon || strchr(colon + 1, ':')) {
		errno = EINVAL;
		return -1;
	}
	major_length = (size_t)(colon - text);
	if (!major_length || major_length >= sizeof(major_text)) {
		errno = EINVAL;
		return -1;
	}
	memcpy(major_text, text, major_length);
	major_text[major_length] = '\0';
	if (swapz_primary_parse_u64(major_text, &major_number) < 0 ||
	    swapz_primary_parse_u64(colon + 1, &minor_number) < 0 ||
	    major_number > UINT_MAX || minor_number > UINT_MAX) {
		errno = EINVAL;
		return -1;
	}
	*device = makedev((unsigned int)major_number,
			  (unsigned int)minor_number);
	if (major(*device) != major_number || minor(*device) != minor_number) {
		errno = ERANGE;
		return -1;
	}
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

static int swapz_primary_persistent_fs_magic(long type)
{
	switch ((unsigned long)type) {
	case EXT2_SUPER_MAGIC:
	case XFS_SUPER_MAGIC:
	case F2FS_SUPER_MAGIC:
		return 1;
	default:
		return 0;
	}
}

static int swapz_primary_path_format(char *path, size_t capacity,
				     const char *format, ...)
{
	va_list arguments;
	int length;

	va_start(arguments, format);
	length = vsnprintf(path, capacity, format, arguments);
	va_end(arguments);
	if (length < 0 || (size_t)length >= capacity) {
		errno = ENAMETOOLONG;
		return -1;
	}
	return 0;
}

static int swapz_primary_read_sysfs_text(const char *path, char *buffer,
					size_t capacity)
{
	size_t length = 0;
	int fd;

	if (!path || !buffer || capacity < 2U) {
		errno = EINVAL;
		return -1;
	}
	fd = open(path, O_RDONLY | O_CLOEXEC | O_NOFOLLOW);
	if (fd < 0)
		return -1;
	while (length + 1U < capacity) {
		ssize_t count = read(fd, buffer + length, capacity - length - 1U);

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
		length += (size_t)count;
	}
	if (length + 1U == capacity) {
		close(fd);
		errno = EOVERFLOW;
		return -1;
	}
	if (close(fd) < 0)
		return -1;
	while (length && (buffer[length - 1U] == '\n' ||
			  buffer[length - 1U] == '\r'))
		--length;
	buffer[length] = '\0';
	return 0;
}

static int swapz_primary_sysfs_dev_number(const char *path, dev_t *device)
{
	char buffer[64];

	if (!device || swapz_primary_read_sysfs_text(path, buffer,
						     sizeof(buffer)) < 0)
		return -1;
	return swapz_primary_parse_dev_number(buffer, device);
}

struct swapz_primary_mount_facts {
	dev_t root_device;
	int root_mount_seen;
	int target_mounted;
};

static int swapz_primary_parse_mountinfo(const char *text,
					       dev_t target_device,
					       struct swapz_primary_mount_facts *facts)
{
	const char *line = text;
	struct swapz_primary_mount_facts parsed = {0};

	if (!text || !facts)
		return -1;
	while (*line) {
		char buffer[8192];
		char *fields[64];
		char *separator;
		size_t length;
		size_t field_count = 0;
		size_t i;
		size_t separator_index = SIZE_MAX;
		uint64_t mount_id;
		uint64_t parent_id;
		dev_t mounted_device;
		const char *end = strchr(line, '\n');

		length = end ? (size_t)(end - line) : strlen(line);
		if (!length || length >= sizeof(buffer))
			return -1;
		memcpy(buffer, line, length);
		buffer[length] = '\0';
		line = end ? end + 1 : line + length;
		separator = strstr(buffer, " - ");
		if (!separator || strstr(separator + 3, " - "))
			return -1;
		if (swapz_primary_split_fields(buffer, fields,
					      sizeof(fields) / sizeof(fields[0]),
					      &field_count) < 0 || field_count < 10U ||
		    swapz_primary_parse_u64(fields[0], &mount_id) < 0 ||
		    swapz_primary_parse_u64(fields[1], &parent_id) < 0 ||
		    !mount_id || !parent_id ||
		    swapz_primary_parse_dev_number(fields[2], &mounted_device) < 0 ||
		    !fields[3][0] || fields[4][0] != '/')
			return -1;
		for (i = 0; i < field_count; ++i) {
			if (strcmp(fields[i], "-"))
				continue;
			if (separator_index != SIZE_MAX)
				return -1;
			separator_index = i;
		}
		if (separator_index < 6U || separator_index + 3U >= field_count)
			return -1;
		if (mounted_device == target_device)
			parsed.target_mounted = 1;
		if (!strcmp(fields[4], "/")) {
			if (parsed.root_mount_seen)
				return -1;
			parsed.root_mount_seen = 1;
			parsed.root_device = mounted_device;
		}
	}
	if (!parsed.root_mount_seen)
		return -1;
	*facts = parsed;
	return 0;
}

static int swapz_primary_read_mount_facts(
	struct swapz_primary_mount_facts *facts)
{
#ifdef SWAPZ_PRIMARY_ROOTLESS_TEST
	(void)facts;
	errno = ENODEV;
	return -1;
#else
	char buffer[SWAPZ_PRIMARY_MOUNTINFO_BUFFER_BYTES];
	size_t used = 0;
	int fd = open("/proc/self/mountinfo", O_RDONLY | O_CLOEXEC | O_NOFOLLOW);

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
	return swapz_primary_parse_mountinfo(buffer, makedev(8U, 4U), facts);
#endif
}

static int swapz_primary_dm_block_name(const char *name)
{
	const unsigned char *cursor;

	if (!name || strncmp(name, "dm-", 3U) || !name[3])
		return 0;
	for (cursor = (const unsigned char *)name + 3U; *cursor; ++cursor)
		if (*cursor < '0' || *cursor > '9')
			return 0;
	return 1;
}

static int swapz_primary_mapper_identity_is_swapz(const char *name,
						 const char *uuid)
{
	const unsigned char *cursor;

	if (!name || !name[0] || !uuid)
		return -1;
	for (cursor = (const unsigned char *)name; *cursor; ++cursor)
		if (*cursor < 0x20U || *cursor == 0x7fU || *cursor == '/')
			return -1;
	for (cursor = (const unsigned char *)uuid; *cursor; ++cursor)
		if (*cursor < 0x20U || *cursor == 0x7fU)
			return -1;
	return !strncmp(name, "swapz-", 6U) ||
	       !strncmp(uuid, "SWAPZ-", 6U);
}

static int swapz_primary_read_module_mapper_inventory(
	int *module_loaded, int *swapz_mapper_present)
{
#ifdef SWAPZ_PRIMARY_ROOTLESS_TEST
	(void)module_loaded;
	(void)swapz_mapper_present;
	errno = ENODEV;
	return -1;
#else
	struct dirent *entry;
	struct stat module_info;
	DIR *block_directory;
	unsigned int mapper_count = 0;
	int saved_errno = 0;

	if (!module_loaded || !swapz_mapper_present) {
		errno = EINVAL;
		return -1;
	}
	*module_loaded = 0;
	*swapz_mapper_present = 0;
	if (stat("/sys/module/dm_swapz", &module_info) == 0) {
		if (!S_ISDIR(module_info.st_mode)) {
			errno = EINVAL;
			return -1;
		}
		*module_loaded = 1;
	} else if (errno != ENOENT) {
		return -1;
	}
	block_directory = opendir("/sys/block");
	if (!block_directory)
		return -1;
	errno = 0;
	while ((entry = readdir(block_directory)) != NULL) {
		char name_path[PATH_MAX];
		char uuid_path[PATH_MAX];
		char mapper_name[128];
		char mapper_uuid[256];
		int identity;

		if (!swapz_primary_dm_block_name(entry->d_name))
			continue;
		if (++mapper_count > SWAPZ_PRIMARY_DM_MAPPERS_MAX) {
			errno = EOVERFLOW;
			break;
		}
		if (swapz_primary_path_format(name_path, sizeof(name_path),
					      "/sys/block/%s/dm/name",
					      entry->d_name) < 0 ||
		    swapz_primary_path_format(uuid_path, sizeof(uuid_path),
					      "/sys/block/%s/dm/uuid",
					      entry->d_name) < 0 ||
		    swapz_primary_read_sysfs_text(name_path, mapper_name,
						      sizeof(mapper_name)) < 0 ||
		    swapz_primary_read_sysfs_text(uuid_path, mapper_uuid,
						      sizeof(mapper_uuid)) < 0) {
			if (!errno)
				errno = EIO;
			break;
		}
		identity = swapz_primary_mapper_identity_is_swapz(mapper_name,
								   mapper_uuid);
		if (identity < 0) {
			errno = EINVAL;
			break;
		}
		if (identity)
			*swapz_mapper_present = 1;
		errno = 0;
	}
	saved_errno = errno;
	if (closedir(block_directory) < 0)
		return -1;
	if (saved_errno) {
		errno = saved_errno;
		return -1;
	}
	return 0;
#endif
}

static int swapz_primary_sysfs_directory_empty(const char *path,
					      int missing_is_empty)
{
	struct dirent *entry;
	DIR *directory = opendir(path);
	int read_error = 0;

	if (!directory)
		return missing_is_empty && errno == ENOENT;
	errno = 0;
	while ((entry = readdir(directory)) != NULL) {
		if (!strcmp(entry->d_name, ".") || !strcmp(entry->d_name, ".."))
			continue;
		read_error = ENOTEMPTY;
		break;
	}
	if (!read_error && errno)
		read_error = errno;
	if (closedir(directory) < 0 && !read_error)
		read_error = errno;
	if (read_error) {
		errno = read_error;
		return 0;
	}
	return 1;
}

static int swapz_primary_recovery_source_chain(
	const char *sysfs_root, dev_t source_device, dev_t target_device,
	dev_t *physical_parent_device)
{
	char devices_root[PATH_MAX];
	char block_root[PATH_MAX];
	char link_path[PATH_MAX];
	char node_path[PATH_MAX];
	char parent_path[PATH_MAX];
	char source_realpath[PATH_MAX];
	char device_path[PATH_MAX];
	char device_realpath[PATH_MAX];
	char path[PATH_MAX];
	char *slash;
	char *resolved_devices_root;
	dev_t observed_source;
	dev_t observed_parent;
	struct stat link_info;
	struct stat queue_info;
	uint64_t partition_number;
	size_t devices_root_length;

	if (!sysfs_root || !physical_parent_device ||
	    (major(source_device) == 0U && minor(source_device) == 0U) ||
	    ((major(target_device) != 0U || minor(target_device) != 0U) &&
	     source_device == target_device)) {
		errno = EINVAL;
		return 0;
	}
	if (swapz_primary_path_format(devices_root, sizeof(devices_root),
				      "%s/devices", sysfs_root) < 0 ||
	    swapz_primary_path_format(block_root, sizeof(block_root),
				      "%s/dev/block", sysfs_root) < 0 ||
	    swapz_primary_path_format(link_path, sizeof(link_path), "%s/%u:%u",
				      block_root, major(source_device),
				      minor(source_device)) < 0)
		return 0;
	if (!realpath(devices_root, path))
		return 0;
	resolved_devices_root = strdup(path);
	if (!resolved_devices_root)
		return 0;
	devices_root_length = strlen(resolved_devices_root);
	if (!realpath(link_path, source_realpath) ||
	    strncmp(source_realpath, resolved_devices_root,
		    devices_root_length) ||
	    source_realpath[devices_root_length] != '/')
		goto rejected;
	if (swapz_primary_path_format(path, sizeof(path), "%s/dev",
				      source_realpath) < 0 ||
	    swapz_primary_sysfs_dev_number(path, &observed_source) < 0 ||
	    observed_source != source_device)
		goto rejected;
	if (swapz_primary_path_format(path, sizeof(path), "%s/partition",
				      source_realpath) < 0 ||
	    swapz_primary_read_sysfs_text(path, node_path,
					     sizeof(node_path)) < 0 ||
	    swapz_primary_parse_u64(node_path, &partition_number) < 0 ||
	    partition_number == 0U)
		goto rejected;
	if (swapz_primary_path_format(parent_path, sizeof(parent_path), "%s",
				      source_realpath) < 0)
		goto rejected;
	slash = strrchr(parent_path, '/');
	if (!slash || slash == parent_path)
		goto rejected;
	*slash = '\0';
	if (swapz_primary_path_format(path, sizeof(path), "%s/dev",
				      parent_path) < 0 ||
	    swapz_primary_sysfs_dev_number(path, &observed_parent) < 0 ||
	    observed_parent == source_device ||
	    ((major(target_device) != 0U || minor(target_device) != 0U) &&
	     observed_parent == target_device))
		goto rejected;
	if (swapz_primary_path_format(device_path, sizeof(device_path),
				       "%s/device", parent_path) < 0 ||
	    lstat(device_path, &link_info) < 0 || !S_ISLNK(link_info.st_mode) ||
	    !realpath(device_path, device_realpath))
		goto rejected;
	if (strncmp(device_realpath, resolved_devices_root,
		    devices_root_length) ||
	    device_realpath[devices_root_length] != '/' ||
	    strstr(device_realpath, "/virtual/") != NULL)
		goto rejected;
	if (swapz_primary_path_format(path, sizeof(path), "%s/queue",
				      parent_path) < 0 ||
	    stat(path, &queue_info) < 0 || !S_ISDIR(queue_info.st_mode))
		goto rejected;
	if (swapz_primary_path_format(path, sizeof(path), "%s/holders",
				      source_realpath) < 0 ||
	    !swapz_primary_sysfs_directory_empty(path, 0) ||
	    swapz_primary_path_format(path, sizeof(path), "%s/slaves",
				      source_realpath) < 0 ||
	    !swapz_primary_sysfs_directory_empty(path, 1) ||
	    swapz_primary_path_format(path, sizeof(path), "%s/holders",
				      parent_path) < 0 ||
	    !swapz_primary_sysfs_directory_empty(path, 0) ||
	    swapz_primary_path_format(path, sizeof(path), "%s/slaves",
				      parent_path) < 0 ||
	    !swapz_primary_sysfs_directory_empty(path, 1))
		goto rejected;
	*physical_parent_device = observed_parent;
	free(resolved_devices_root);
	return 1;

rejected:
	free(resolved_devices_root);
	return 0;
}

static int swapz_primary_recovery_preflight(
	int *directory_safe, int *persistent_filesystem,
	unsigned int *filesystem_major, unsigned int *filesystem_minor,
	int *directly_not_target, int *source_chain_checked,
	unsigned int *physical_parent_major, unsigned int *physical_parent_minor,
	int *active_marker_clear)
{
#ifdef SWAPZ_PRIMARY_ROOTLESS_TEST
	(void)directory_safe;
	(void)persistent_filesystem;
	(void)filesystem_major;
	(void)filesystem_minor;
	(void)directly_not_target;
	(void)source_chain_checked;
	(void)physical_parent_major;
	(void)physical_parent_minor;
	(void)active_marker_clear;
	errno = ENODEV;
	return -1;
#else
	struct stat directory_info;
	struct statfs filesystem_info;
	struct stat marker_info;
	dev_t source_device;
	dev_t source_parent_device = 0;
	int recovery_fd;
	int marker_result;

	if (!directory_safe || !persistent_filesystem || !filesystem_major ||
	    !filesystem_minor || !directly_not_target || !source_chain_checked ||
	    !physical_parent_major || !physical_parent_minor ||
	    !active_marker_clear) {
		errno = EINVAL;
		return -1;
	}
	*directory_safe = 0;
	*persistent_filesystem = 0;
	*filesystem_major = 0;
	*filesystem_minor = 0;
	*directly_not_target = 0;
	*source_chain_checked = 0;
	*physical_parent_major = 0;
	*physical_parent_minor = 0;
	*active_marker_clear = 0;
	recovery_fd = swapz_primary_recovery_base_open(
		SWAPZ_PRIMARY_RECOVERY_BASE, 0);
	if (recovery_fd < 0)
		return -1;
	if (fstat(recovery_fd, &directory_info) < 0 ||
	    fstatfs(recovery_fd, &filesystem_info) < 0) {
		int saved_errno = errno;

		close(recovery_fd);
		errno = saved_errno;
		return -1;
	}
	*directory_safe = 1;
	*persistent_filesystem =
		swapz_primary_persistent_fs_magic(filesystem_info.f_type);
	*filesystem_major = major(directory_info.st_dev);
	*filesystem_minor = minor(directory_info.st_dev);
	*directly_not_target =
		(*filesystem_major != 0U || *filesystem_minor != 0U) &&
		!(*filesystem_major == 8U && *filesystem_minor == 4U);
	source_device = makedev(*filesystem_major, *filesystem_minor);
	if (*persistent_filesystem && *directly_not_target &&
	    swapz_primary_recovery_source_chain(
		    "/sys", source_device, makedev(8U, 4U),
		    &source_parent_device)) {
		*source_chain_checked = 1;
		*physical_parent_major = major(source_parent_device);
		*physical_parent_minor = minor(source_parent_device);
	}
	marker_result = fstatat(recovery_fd,
				"partition-7fb9401d-04.active", &marker_info,
				AT_SYMLINK_NOFOLLOW);
	if (marker_result < 0 && errno == ENOENT)
		*active_marker_clear = 1;
	if (close(recovery_fd) < 0)
		return -1;
	return 0;
#endif
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

int swapz_primary_replace_record_at(int recovery_fd, const char *name,
				    const char *run_id, const char *record,
				    uid_t expected_owner)
{
	struct stat directory_info;
	struct stat old_info;
	struct stat current_info;
	struct stat temporary_info;
	char temporary_name[256];
	const unsigned char *name_cursor;
	const char *record_cursor = record;
	size_t remaining;
	int old_present = 0;
	int temporary_identity_valid = 0;
	int fd = -1;
	int saved_errno;
	int length;
	size_t name_length;

	if (recovery_fd < 0 || !name || !run_id || !record ||
	    !swapz_primary_valid_run_id(run_id)) {
		errno = EINVAL;
		return -1;
	}
	remaining = strnlen(record, SWAPZ_PRIMARY_STATE_RECORD_MAX);
	if (remaining == SWAPZ_PRIMARY_STATE_RECORD_MAX) {
		errno = EOVERFLOW;
		return -1;
	}
	name_length = strnlen(name, 128U);
	if (!name_length || name_length == 128U || name[0] == '.') {
		errno = EINVAL;
		return -1;
	}
	for (name_cursor = (const unsigned char *)name; *name_cursor;
	     ++name_cursor)
		if (!((*name_cursor >= 'a' && *name_cursor <= 'z') ||
		      (*name_cursor >= 'A' && *name_cursor <= 'Z') ||
		      (*name_cursor >= '0' && *name_cursor <= '9') ||
		      *name_cursor == '.' || *name_cursor == '_' ||
		      *name_cursor == '-')) {
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
	length = snprintf(temporary_name, sizeof(temporary_name), ".%s.%s.tmp",
			  name, run_id);
	if (length < 0 || (size_t)length >= sizeof(temporary_name)) {
		errno = ENAMETOOLONG;
		return -1;
	}
	if (fstatat(recovery_fd, name, &old_info, AT_SYMLINK_NOFOLLOW) == 0) {
		if (!S_ISREG(old_info.st_mode) || old_info.st_uid != expected_owner ||
		    (old_info.st_mode & 0777U) != 0600U || old_info.st_nlink != 1) {
			errno = EPERM;
			return -1;
		}
		old_present = 1;
	} else if (errno != ENOENT) {
		return -1;
	}
	fd = openat(recovery_fd, temporary_name,
		    O_WRONLY | O_CREAT | O_EXCL | O_NOFOLLOW | O_CLOEXEC, 0600);
	if (fd < 0)
		return -1;
	if (fstat(fd, &temporary_info) < 0) {
		saved_errno = errno;
		goto failed;
	}
	if (!S_ISREG(temporary_info.st_mode) ||
	    temporary_info.st_uid != expected_owner ||
	    (temporary_info.st_mode & 0777U) != 0600U ||
	    temporary_info.st_nlink != 1) {
		saved_errno = EPERM;
		goto failed;
	}
	temporary_identity_valid = 1;
	while (remaining) {
		ssize_t count = write(fd, record_cursor, remaining);

		if (count < 0 && errno == EINTR)
			continue;
		if (count <= 0) {
			saved_errno = count < 0 ? errno : EIO;
			goto failed;
		}
		record_cursor += count;
		remaining -= (size_t)count;
	}
	if (fsync(fd) < 0) {
		saved_errno = errno;
		goto failed;
	}
	if (fstatat(recovery_fd, temporary_name, &current_info,
		    AT_SYMLINK_NOFOLLOW) < 0) {
		saved_errno = errno;
		goto failed;
	}
	if (current_info.st_dev != temporary_info.st_dev ||
	    current_info.st_ino != temporary_info.st_ino ||
	    !S_ISREG(current_info.st_mode) || current_info.st_nlink != 1) {
		saved_errno = EPERM;
		goto failed;
	}
	if (old_present) {
		if (fstatat(recovery_fd, name, &current_info,
			    AT_SYMLINK_NOFOLLOW) < 0) {
			saved_errno = errno;
			goto failed;
		}
		if (current_info.st_dev != old_info.st_dev ||
		    current_info.st_ino != old_info.st_ino ||
		    !S_ISREG(current_info.st_mode) ||
		    current_info.st_uid != expected_owner ||
		    (current_info.st_mode & 0777U) != 0600U ||
		    current_info.st_nlink != 1) {
			saved_errno = EPERM;
			goto failed;
		}
	} else {
		if (fstatat(recovery_fd, name, &current_info,
			    AT_SYMLINK_NOFOLLOW) == 0) {
			saved_errno = EEXIST;
			goto failed;
		}
		if (errno != ENOENT) {
			saved_errno = errno;
			goto failed;
		}
	}
	if (renameat(recovery_fd, temporary_name, recovery_fd, name) < 0) {
		saved_errno = errno;
		goto failed;
	}
	if (close(fd) < 0)
		return -1;
	return fsync(recovery_fd);

failed:
	if (fd >= 0) {
		struct stat named_info;

		if (temporary_identity_valid &&
		    fstatat(recovery_fd, temporary_name, &named_info,
			    AT_SYMLINK_NOFOLLOW) == 0 &&
		    named_info.st_dev == temporary_info.st_dev &&
		    named_info.st_ino == temporary_info.st_ino)
			(void)unlinkat(recovery_fd, temporary_name, 0);
		(void)close(fd);
	}
	errno = saved_errno;
	return -1;
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

static int swapz_primary_state_lock_valid(int recovery_fd, int lock_fd,
					  uid_t expected_owner)
{
	struct stat directory_info;
	struct stat held_lock_info;
	struct stat named_lock_info;
	char lock_name[64];

	if (recovery_fd < 0 || lock_fd < 0 ||
	    fstat(recovery_fd, &directory_info) < 0 ||
	    fstat(lock_fd, &held_lock_info) < 0)
		return 0;
	if (!S_ISDIR(directory_info.st_mode) ||
	    directory_info.st_uid != expected_owner ||
	    (directory_info.st_mode & 0777U) != 0700U ||
	    !S_ISREG(held_lock_info.st_mode) ||
	    held_lock_info.st_uid != expected_owner ||
	    (held_lock_info.st_mode & 0777U) != 0600U ||
	    held_lock_info.st_nlink != 1) {
		errno = EPERM;
		return 0;
	}
	if (snprintf(lock_name, sizeof(lock_name), "partition-%s.lock",
		     SWAPZ_PRIMARY_PARTUUID) < 0 ||
	    fstatat(recovery_fd, lock_name, &named_lock_info,
		    AT_SYMLINK_NOFOLLOW) < 0)
		return 0;
	if (!S_ISREG(named_lock_info.st_mode) ||
	    named_lock_info.st_uid != expected_owner ||
	    (named_lock_info.st_mode & 0777U) != 0600U ||
	    named_lock_info.st_nlink != 1 ||
	    named_lock_info.st_dev != held_lock_info.st_dev ||
	    named_lock_info.st_ino != held_lock_info.st_ino) {
		errno = EPERM;
		return 0;
	}
	return flock(lock_fd, LOCK_EX | LOCK_NB) == 0;
}

static int swapz_primary_record_read_at(int recovery_fd, const char *name,
					uid_t expected_owner, char *record,
					size_t capacity, size_t *length,
					struct stat *identity)
{
	struct stat opened_info;
	struct stat named_info;
	struct stat after_info;
	unsigned char extra;
	size_t completed = 0;
	int fd;

	if (recovery_fd < 0 || !name || !record || capacity < 2U || !length) {
		errno = EINVAL;
		return -1;
	}
	if (fstatat(recovery_fd, name, &named_info, AT_SYMLINK_NOFOLLOW) < 0)
		return -1;
	fd = openat(recovery_fd, name, O_RDONLY | O_NOFOLLOW | O_CLOEXEC);
	if (fd < 0)
		return -1;
	if (fstat(fd, &opened_info) < 0)
		goto failed;
	if (!S_ISREG(opened_info.st_mode) ||
	    opened_info.st_uid != expected_owner ||
	    (opened_info.st_mode & 0777U) != 0600U ||
	    opened_info.st_nlink != 1 || opened_info.st_size <= 0 ||
	    (uint64_t)opened_info.st_size >= (uint64_t)capacity ||
	    (uint64_t)opened_info.st_size > SWAPZ_PRIMARY_STATE_RECORD_MAX ||
	    opened_info.st_dev != named_info.st_dev ||
	    opened_info.st_ino != named_info.st_ino) {
		errno = EPERM;
		goto failed;
	}
	while (completed < (size_t)opened_info.st_size) {
		ssize_t count = pread(fd, record + completed,
				      (size_t)opened_info.st_size - completed,
				      (off_t)completed);

		if (count < 0 && errno == EINTR)
			continue;
		if (count <= 0) {
			if (!count)
				errno = EIO;
			goto failed;
		}
		completed += (size_t)count;
	}
	for (;;) {
		ssize_t count = pread(fd, &extra, sizeof(extra),
				      opened_info.st_size);

		if (count < 0 && errno == EINTR)
			continue;
		if (count != 0) {
			if (count > 0)
				errno = EOVERFLOW;
			goto failed;
		}
		break;
	}
	if (fstat(fd, &after_info) < 0 ||
	    fstatat(recovery_fd, name, &named_info, AT_SYMLINK_NOFOLLOW) < 0)
		goto failed;
	if (after_info.st_dev != opened_info.st_dev ||
	    after_info.st_ino != opened_info.st_ino ||
	    after_info.st_size != opened_info.st_size ||
	    after_info.st_mtim.tv_sec != opened_info.st_mtim.tv_sec ||
	    after_info.st_mtim.tv_nsec != opened_info.st_mtim.tv_nsec ||
	    after_info.st_ctim.tv_sec != opened_info.st_ctim.tv_sec ||
	    after_info.st_ctim.tv_nsec != opened_info.st_ctim.tv_nsec ||
	    after_info.st_uid != expected_owner ||
	    (after_info.st_mode & 0777U) != 0600U ||
	    !S_ISREG(after_info.st_mode) || after_info.st_nlink != 1 ||
	    named_info.st_dev != opened_info.st_dev ||
	    named_info.st_ino != opened_info.st_ino ||
	    named_info.st_uid != expected_owner ||
	    (named_info.st_mode & 0777U) != 0600U ||
	    !S_ISREG(named_info.st_mode) || named_info.st_nlink != 1) {
		errno = EPERM;
		goto failed;
	}
	if (close(fd) < 0)
		return -1;
	*length = completed;
	record[completed] = '\0';
	if (identity)
		*identity = opened_info;
	return 0;

failed:
	{
		int saved_errno = errno;

		(void)close(fd);
		errno = saved_errno;
		return -1;
	}
}

static int swapz_primary_owner_claim_matches_at(int recovery_fd,
						const char *run_id,
						uid_t expected_owner)
{
	char active_name[64];
	char consumed_name[64];
	char expected[192];
	char active_record[256];
	char consumed_record[256];
	size_t active_length;
	size_t consumed_length;
	int expected_length;

	if (!swapz_primary_valid_run_id(run_id)) {
		errno = EINVAL;
		return 0;
	}
	if (snprintf(active_name, sizeof(active_name), "partition-%s.active",
		     SWAPZ_PRIMARY_PARTUUID) < 0 ||
	    snprintf(consumed_name, sizeof(consumed_name), "consumed-%s.json",
		     run_id) < 0)
		return 0;
	expected_length = snprintf(expected, sizeof(expected),
				   "{\"major\":8,\"minor\":4,"
				   "\"partuuid\":\"%s\",\"run_id\":\"%s\"}\n",
				   SWAPZ_PRIMARY_PARTUUID, run_id);
	if (expected_length < 0 || (size_t)expected_length >= sizeof(expected)) {
		errno = EOVERFLOW;
		return 0;
	}
	if (swapz_primary_record_read_at(recovery_fd, active_name,
					 expected_owner, active_record,
					 sizeof(active_record), &active_length,
					 NULL) < 0 ||
	    swapz_primary_record_read_at(recovery_fd, consumed_name,
					 expected_owner, consumed_record,
					 sizeof(consumed_record), &consumed_length,
					 NULL) < 0)
		return 0;
	if (active_length != (size_t)expected_length ||
	    consumed_length != (size_t)expected_length ||
	    memcmp(active_record, expected, active_length) ||
	    memcmp(consumed_record, expected, consumed_length)) {
		errno = EPERM;
		return 0;
	}
	return 1;
}

static int swapz_primary_valid_sha256(const char *digest)
{
	unsigned int i;

	if (!digest || strnlen(digest, 65U) != 64U)
		return 0;
	for (i = 0; i < 64U; ++i)
		if (!((digest[i] >= '0' && digest[i] <= '9') ||
		      (digest[i] >= 'a' && digest[i] <= 'f')))
			return 0;
	return 1;
}

static int swapz_primary_header_backup_name(const char *run_id,
						    char *name, size_t capacity)
{
	int length;

	if (!swapz_primary_valid_run_id(run_id) || !name || !capacity) {
		errno = EINVAL;
		return -1;
	}
	length = snprintf(name, capacity, "block0-%s.bin", run_id);
	if (length < 0 || (size_t)length >= capacity) {
		errno = ENAMETOOLONG;
		return -1;
	}
	return 0;
}

int swapz_primary_header_backup_read_at(
	int recovery_fd, int lock_fd, const char *run_id,
	const char *expected_sha256, uid_t expected_owner,
	unsigned char header[SWAPZ_PRIMARY_BLOCK_BYTES])
{
	unsigned char saved[SWAPZ_PRIMARY_BLOCK_BYTES + 1U];
	char name[64];
	char digest[65];
	size_t length;

	if (recovery_fd < 0 || lock_fd < 0 || !header ||
	    !swapz_primary_valid_sha256(expected_sha256) ||
	    swapz_primary_header_backup_name(run_id, name, sizeof(name)) < 0) {
		errno = EINVAL;
		return -1;
	}
	if (!swapz_primary_state_lock_valid(recovery_fd, lock_fd,
					    expected_owner) ||
	    !swapz_primary_owner_claim_matches_at(recovery_fd, run_id,
						 expected_owner))
		return -1;
	if (swapz_primary_record_read_at(recovery_fd, name, expected_owner,
					 (char *)saved, sizeof(saved), &length,
					 NULL) < 0)
		return -1;
	if (length != SWAPZ_PRIMARY_BLOCK_BYTES ||
	    swapz_primary_sha256(saved, length, digest) < 0)
		return -1;
	if (strcmp(digest, expected_sha256)) {
		errno = EBADMSG;
		return -1;
	}
	memcpy(header, saved, SWAPZ_PRIMARY_BLOCK_BYTES);
	return 0;
}

int swapz_primary_header_backup_write_at(
	int recovery_fd, int lock_fd, const char *run_id,
	const unsigned char header[SWAPZ_PRIMARY_BLOCK_BYTES],
	const char *expected_sha256, uid_t expected_owner)
{
	struct stat directory_info;
	struct stat temporary_info;
	struct stat named_info;
	unsigned char verified[SWAPZ_PRIMARY_BLOCK_BYTES];
	char name[64];
	char temporary[96];
	char digest[65];
	int fd = -1;
	int temporary_identity_valid = 0;
	int saved_errno = 0;
	int length;
	size_t written = 0;

	if (recovery_fd < 0 || lock_fd < 0 || !header ||
	    !swapz_primary_valid_sha256(expected_sha256) ||
	    swapz_primary_header_backup_name(run_id, name, sizeof(name)) < 0) {
		errno = EINVAL;
		return -1;
	}
	if (!swapz_primary_state_lock_valid(recovery_fd, lock_fd,
					    expected_owner) ||
	    !swapz_primary_owner_claim_matches_at(recovery_fd, run_id,
						 expected_owner))
		return -1;
	if (swapz_primary_sha256(header, SWAPZ_PRIMARY_BLOCK_BYTES, digest) < 0)
		return -1;
	if (strcmp(digest, expected_sha256)) {
		errno = EBADMSG;
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
	length = snprintf(temporary, sizeof(temporary), ".%s.%s.tmp", name,
			  run_id);
	if (length < 0 || (size_t)length >= sizeof(temporary)) {
		errno = ENAMETOOLONG;
		return -1;
	}
	if (fstatat(recovery_fd, name, &named_info, AT_SYMLINK_NOFOLLOW) == 0) {
		errno = EEXIST;
		return -1;
	}
	if (errno != ENOENT)
		return -1;
	fd = openat(recovery_fd, temporary,
		    O_WRONLY | O_CREAT | O_EXCL | O_NOFOLLOW | O_CLOEXEC, 0600);
	if (fd < 0)
		return -1;
	if (fstat(fd, &temporary_info) < 0)
		goto failed;
	if (!S_ISREG(temporary_info.st_mode) ||
	    temporary_info.st_uid != expected_owner ||
	    (temporary_info.st_mode & 0777U) != 0600U ||
	    temporary_info.st_nlink != 1) {
		errno = EPERM;
		goto failed;
	}
	temporary_identity_valid = 1;
	while (written < SWAPZ_PRIMARY_BLOCK_BYTES) {
		ssize_t count = write(fd, header + written,
				     SWAPZ_PRIMARY_BLOCK_BYTES - written);

		if (count < 0 && errno == EINTR)
			continue;
		if (count <= 0) {
			if (!count)
				errno = EIO;
			goto failed;
		}
		written += (size_t)count;
	}
	if (fsync(fd) < 0 ||
	    fstatat(recovery_fd, temporary, &named_info,
		    AT_SYMLINK_NOFOLLOW) < 0)
		goto failed;
	if (named_info.st_dev != temporary_info.st_dev ||
	    named_info.st_ino != temporary_info.st_ino ||
	    !S_ISREG(named_info.st_mode) ||
	    named_info.st_uid != expected_owner ||
	    (named_info.st_mode & 0777U) != 0600U ||
	    named_info.st_nlink != 1 ||
	    named_info.st_size != (off_t)SWAPZ_PRIMARY_BLOCK_BYTES) {
		errno = EPERM;
		goto failed;
	}
	if (close(fd) < 0) {
		saved_errno = errno;
		fd = -1;
		errno = saved_errno;
		goto failed;
	}
	fd = -1;
	if (renameat2(recovery_fd, temporary, recovery_fd, name,
		       RENAME_NOREPLACE) < 0) {
		saved_errno = errno;
		goto failed;
	}
	if (fsync(recovery_fd) < 0 ||
	    swapz_primary_header_backup_read_at(recovery_fd, lock_fd, run_id,
						expected_sha256, expected_owner,
						verified) < 0)
		return -1;
	if (memcmp(header, verified, sizeof(verified))) {
		errno = EIO;
		return -1;
	}
	return 0;

failed:
	if (!saved_errno)
		saved_errno = errno;
	if (temporary_identity_valid &&
	    fstatat(recovery_fd, temporary, &named_info,
		    AT_SYMLINK_NOFOLLOW) == 0 &&
	    named_info.st_dev == temporary_info.st_dev &&
	    named_info.st_ino == temporary_info.st_ino) {
		(void)unlinkat(recovery_fd, temporary, 0);
		(void)fsync(recovery_fd);
	}
	if (fd >= 0)
		(void)close(fd);
	errno = saved_errno;
	return -1;
}

int swapz_primary_state_write_at(int recovery_fd, int lock_fd,
				 const struct swapz_primary_state *next,
				 uid_t expected_owner)
{
	struct swapz_primary_state current;
	char current_record[SWAPZ_PRIMARY_STATE_RECORD_MAX + 1U];
	char next_record[SWAPZ_PRIMARY_STATE_RECORD_MAX + 1U];
	size_t current_length;
	int length;

	if (!swapz_primary_state_valid(next)) {
		errno = EINVAL;
		return -1;
	}
	if (!swapz_primary_state_lock_valid(recovery_fd, lock_fd,
					    expected_owner))
		return -1;
	if (!swapz_primary_owner_claim_matches_at(recovery_fd, next->run_id,
						 expected_owner))
		return -1;
	if (swapz_primary_record_read_at(recovery_fd, "primary-state.json",
					 expected_owner, current_record,
					 sizeof(current_record), &current_length,
					 NULL) == 0) {
		if (swapz_primary_state_parse(current_record, current_length,
					      &current) < 0 ||
		    !swapz_primary_state_transition_allowed(&current, next)) {
			errno = EPERM;
			return -1;
		}
	} else if (errno != ENOENT ||
		   next->stage != SWAPZ_PRIMARY_STAGE_READY ||
		   next->has_recovery_previous_stage) {
		return -1;
	}
	length = swapz_primary_state_format(next, next_record,
					   sizeof(next_record));
	if (length < 0)
		return -1;
	if (swapz_primary_replace_record_at(recovery_fd, "primary-state.json",
					   next->run_id, next_record,
					   expected_owner) < 0)
		return -1;
	return 0;
}

int swapz_primary_release_partition_owner_at(int recovery_fd, int lock_fd,
						     const char *run_id,
						     uid_t expected_owner)
{
	struct swapz_primary_state state;
	struct stat active_info;
	struct stat named_info;
	char state_record[SWAPZ_PRIMARY_STATE_RECORD_MAX + 1U];
	char active_name[64];
	size_t state_length;
	int marker_result;

	if (recovery_fd < 0 || lock_fd < 0 ||
	    !swapz_primary_valid_run_id(run_id)) {
		errno = EINVAL;
		return -1;
	}
	if (!swapz_primary_state_lock_valid(recovery_fd, lock_fd,
					    expected_owner))
		return -1;
	if (!swapz_primary_owner_claim_matches_at(recovery_fd, run_id,
						 expected_owner))
		return -1;
	if (swapz_primary_record_read_at(recovery_fd, "primary-state.json",
					 expected_owner, state_record,
					 sizeof(state_record), &state_length,
					 NULL) < 0)
		return -1;
	if (swapz_primary_state_parse(state_record, state_length, &state) < 0) {
		errno = EINVAL;
		return -1;
	}
	if (state.stage != SWAPZ_PRIMARY_STAGE_COMPLETE ||
	    strcmp(state.run_id, run_id)) {
		errno = EPERM;
		return -1;
	}
	if (snprintf(active_name, sizeof(active_name), "partition-%s.active",
		     SWAPZ_PRIMARY_PARTUUID) < 0)
		return -1;
	if (swapz_primary_record_read_at(recovery_fd, active_name,
					 expected_owner, state_record,
					 sizeof(state_record), &state_length,
					 &active_info) < 0)
		return -1;
	if (fstatat(recovery_fd, active_name, &named_info,
		    AT_SYMLINK_NOFOLLOW) < 0 ||
	    named_info.st_dev != active_info.st_dev ||
	    named_info.st_ino != active_info.st_ino ||
	    !S_ISREG(named_info.st_mode) || named_info.st_nlink != 1) {
		errno = EPERM;
		return -1;
	}
	marker_result = unlinkat(recovery_fd, active_name, 0);
	if (marker_result < 0)
		return -1;
	if (fsync(recovery_fd) < 0)
		return -1;
	if (fstatat(recovery_fd, active_name, &named_info,
		    AT_SYMLINK_NOFOLLOW) == 0 || errno != ENOENT) {
		errno = EIO;
		return -1;
	}
	return 0;
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
	int recovery_directory_safe = 0;
	int recovery_persistent_filesystem = 0;
	unsigned int recovery_filesystem_major = 0;
	unsigned int recovery_filesystem_minor = 0;
	int recovery_directly_not_target = 0;
	int recovery_source_chain_checked = 0;
	unsigned int recovery_physical_parent_major = 0;
	unsigned int recovery_physical_parent_minor = 0;
	int recovery_active_marker_clear = 0;
	int recovery_preflight_read = swapz_primary_recovery_preflight(
		&recovery_directory_safe, &recovery_persistent_filesystem,
		&recovery_filesystem_major, &recovery_filesystem_minor,
		&recovery_directly_not_target, &recovery_source_chain_checked,
		&recovery_physical_parent_major,
		&recovery_physical_parent_minor,
		&recovery_active_marker_clear) == 0;
	struct swapz_primary_mount_facts mount_facts = {0};
	int mount_inventory_read = swapz_primary_read_mount_facts(&mount_facts) == 0;
	int target_not_mounted = mount_inventory_read &&
		!mount_facts.target_mounted;
	dev_t root_physical_parent = 0;
	dev_t target_physical_parent = 0;
	int target_device_chain_checked = target_device_preflight &&
		swapz_primary_recovery_source_chain(
			"/sys", makedev(8U, 4U), 0,
			&target_physical_parent);
	int recovery_same_physical_disk = recovery_source_chain_checked &&
		target_device_chain_checked &&
		makedev(recovery_physical_parent_major,
			recovery_physical_parent_minor) == target_physical_parent;
	int root_mount_source_chain_checked = mount_inventory_read &&
		target_device_chain_checked &&
		swapz_primary_recovery_source_chain(
			"/sys", mount_facts.root_device, makedev(8U, 4U),
			&root_physical_parent);
	int root_same_physical_disk = root_mount_source_chain_checked &&
		root_physical_parent == target_physical_parent;
	int dm_swapz_module_loaded = 0;
	int swapz_mapper_present = 0;
	int module_mapper_inventory_read =
		swapz_primary_read_module_mapper_inventory(
			&dm_swapz_module_loaded, &swapz_mapper_present) == 0;

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
	       "\"recovery_preflight_read\":%s,"
	       "\"recovery_directory_safe\":%s,"
	       "\"recovery_filesystem_supported\":%s,"
	       "\"recovery_filesystem_major\":%u,"
	       "\"recovery_filesystem_minor\":%u,"
	       "\"recovery_directly_not_target\":%s,"
	       "\"recovery_active_marker_clear\":%s,"
	       "\"recovery_source_chain_checked\":%s,"
	       "\"recovery_physical_parent_major\":%u,"
	       "\"recovery_physical_parent_minor\":%u,"
	       "\"recovery_same_physical_disk_as_target\":%s,"
	       "\"target_device_chain_checked\":%s,"
	       "\"target_physical_parent_major\":%u,"
	       "\"target_physical_parent_minor\":%u,"
	       "\"module_mapper_inventory_read\":%s,"
	       "\"dm_swapz_module_loaded\":%s,"
	       "\"swapz_mapper_absent\":%s,"
	       "\"mount_inventory_read\":%s,"
	       "\"target_not_mounted\":%s,"
	       "\"root_mount_device_major\":%u,"
	       "\"root_mount_device_minor\":%u,"
	       "\"root_mount_source_chain_checked\":%s,"
	       "\"root_same_physical_disk_as_target\":%s,"
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
	       recovery_preflight_read ? "true" : "false",
	       recovery_directory_safe ? "true" : "false",
	       recovery_persistent_filesystem ? "true" : "false",
	       recovery_filesystem_major,
	       recovery_filesystem_minor,
	       recovery_directly_not_target ? "true" : "false",
	       recovery_active_marker_clear ? "true" : "false",
	       recovery_source_chain_checked ? "true" : "false",
	       recovery_physical_parent_major,
	       recovery_physical_parent_minor,
	       recovery_same_physical_disk ? "true" : "false",
	       target_device_chain_checked ? "true" : "false",
	       major(target_physical_parent),
	       minor(target_physical_parent),
	       module_mapper_inventory_read ? "true" : "false",
	       dm_swapz_module_loaded ? "true" : "false",
	       module_mapper_inventory_read && !swapz_mapper_present ?
		       "true" : "false",
	       mount_inventory_read ? "true" : "false",
	       target_not_mounted ? "true" : "false",
	       major(mount_facts.root_device),
	       minor(mount_facts.root_device),
	       root_mount_source_chain_checked ? "true" : "false",
	       root_same_physical_disk ? "true" : "false",
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
