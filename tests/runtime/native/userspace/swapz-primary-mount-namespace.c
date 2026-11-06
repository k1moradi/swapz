// SPDX-License-Identifier: GPL-2.0-only
#define _GNU_SOURCE
#include <assert.h>
#include <dirent.h>
#include <errno.h>
#include <fcntl.h>
#include <ftw.h>
#include <limits.h>
#include <linux/stat.h>
#include <stdint.h>
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/syscall.h>
#include <sys/sysmacros.h>
#include <unistd.h>

/*
 * Ubuntu 24.04 userspace headers predate the syscall-name macros. The native
 * fixture intercepts these calls entirely; define the architecture-common
 * Linux syscall numbers only so the synthetic 6.18+ namespace ABI path is
 * compiled and exercised on x86_64 and arm64 CI.
 */
#ifndef SYS_statmount
#define SYS_statmount 457
#endif
#ifndef SYS_listmount
#define SYS_listmount 458
#endif
_Static_assert(SYS_statmount == 457 && SYS_listmount == 458,
	       "fixture syscall numbers must match Linux x86_64/arm64 UAPI");

/*
 * Compile the actual production manager, without SWAPZ_PRIMARY_ROOTLESS_TEST:
 * that macro intentionally disables the production mount reader. Redirect only
 * procfs input to owned regular files; never create a mount, open a block
 * device, or invoke a lifecycle/mutation command.
 */
static char fixture_proc_root[PATH_MAX];
static int fixture_mount_open_error;
static int fixture_task_mount_open_error;
static int fixture_task_mount_open_error_injected;
static int fixture_self_mount_open_error;
static int fixture_inventory_error;
static int fixture_inventory_readdir_error;
static int fixture_inventory_seen_foreign_pid;
static int fixture_task_readdir_error;
static int fixture_task_seen_thread;
static int fixture_task_namespace_reuse_on_stat;
static int fixture_task_namespace_reuse_injected;
static unsigned int fixture_coordinator_task_mountinfo_opens;
static unsigned int fixture_foreign_task_mountinfo_opens;
static int fixture_coordinator_task_mount_fd = -1;
static DIR *fixture_proc_directory;
static DIR *fixture_task_directory;
static int fixture_same_namespace_mount_after_self_snapshot;
static int fixture_same_namespace_mount_injected;
/* Timed synthetic procfs changes; these do not create actual mounts. */
static const char *fixture_peer_mountinfo_before_peer_scan;
static int fixture_peer_mountinfo_before_peer_scan_injected;
static int fixture_mount_open_error_before_peer_scan;
static int fixture_mount_open_error_before_peer_scan_injected;
static const char *fixture_peer_mountinfo_after_peer_scan;
static int fixture_peer_mountinfo_after_peer_scan_injected;
static int fixture_peer_namespace_changes_between_stats;
static int fixture_peer_namespace_changed;
static int fixture_peer_namespace_vanishes_between_stats;
static int fixture_peer_namespace_vanished_between_stats;
static int fixture_peer_namespace_vanishes_on_mountinfo_open;
static int fixture_peer_namespace_vanished_on_mountinfo_open;
static const char *fixture_peer_mountinfo_after_namespace_change;
static int fixture_mount_vanish_on_read;
static int fixture_namespace_stat_error;
static int fixture_mount_read_error;
static int fixture_mount_close_error;
static int fixture_mount_fd = -1;
static int fixture_mount_fd_is_peer_leader;
static int fixture_peer_mountinfo_read_eof;
static unsigned int fixture_peer_mountinfo_completed_reads;
static const char *fixture_regular_swap_path;
static dev_t fixture_regular_swap_device;
static char fixture_self_root[PATH_MAX] = "/";

enum fixture_namespace_kind {
	FIXTURE_NAMESPACE_NONE,
	FIXTURE_NAMESPACE_SELF,
	FIXTURE_NAMESPACE_SELF_TASK,
	FIXTURE_NAMESPACE_FOREIGN_LEADER,
	FIXTURE_NAMESPACE_FOREIGN_TASK,
	FIXTURE_NAMESPACE_KIND_COUNT,
};

static int fixture_namespace_fd = -1;
static enum fixture_namespace_kind fixture_namespace_fd_kind =
	FIXTURE_NAMESPACE_NONE;
static enum fixture_namespace_kind fixture_hidden_namespace_kind =
	FIXTURE_NAMESPACE_NONE;
static dev_t fixture_hidden_namespace_device;
static enum fixture_namespace_kind fixture_namespace_inventory_error_kind =
	FIXTURE_NAMESPACE_NONE;
static int fixture_namespace_inventory_error;
static enum fixture_namespace_kind fixture_root_statx_error_kind =
	FIXTURE_NAMESPACE_NONE;
static int fixture_root_statx_error;
static unsigned int
	fixture_namespace_inventory_scans[FIXTURE_NAMESPACE_KIND_COUNT];

static void fixture_file(const char *relative, const char *contents);

static const char *fixture_path(const char *path, char converted[PATH_MAX])
{
	int length;

	if (strncmp(path, "/proc", 5U) || (path[5] && path[5] != '/'))
		return path;
	length = snprintf(converted, PATH_MAX, "%s%s", fixture_proc_root,
			  path + 5U);
	assert(length >= 0 && length < PATH_MAX);
	return converted;
}

static int fixture_path_has_suffix(const char *path, const char *suffix)
{
	size_t length = strlen(path);
	size_t suffix_length = strlen(suffix);

	return length >= suffix_length &&
	       !strcmp(path + length - suffix_length, suffix) &&
	       (length == suffix_length ||
		path[length - suffix_length - 1U] == '/');
}

static void fixture_track_task_mountinfo_open(const char *path, int fd)
{
	if (fd < 0)
		return;
	if (fixture_path_has_suffix(path, "self/task/65536/mountinfo")) {
		++fixture_coordinator_task_mountinfo_opens;
		fixture_coordinator_task_mount_fd = fd;
	}
	if (fixture_path_has_suffix(path, "3031/task/3032/mountinfo"))
		++fixture_foreign_task_mountinfo_opens;
}

static int fixture_other_mountinfo(const char *path)
{
	static const char *const suffixes[] = {
		"3031/mountinfo",
		"3031/task/3032/mountinfo",
	};
	size_t length = strlen(path);
	size_t index;

	for (index = 0; index < sizeof(suffixes) / sizeof(suffixes[0]); ++index) {
		size_t suffix_length = strlen(suffixes[index]);

		if (length >= suffix_length &&
		    !strcmp(path + length - suffix_length, suffixes[index]) &&
		    (length == suffix_length ||
		     path[length - suffix_length - 1U] == '/'))
			return 1;
	}
	return 0;
}


static enum fixture_namespace_kind fixture_namespace_kind_for_path(
	const char *path)
{
	if (!path)
		return FIXTURE_NAMESPACE_NONE;
	if (strstr(path, "/3031/task/3032/"))
		return FIXTURE_NAMESPACE_FOREIGN_TASK;
	if (strstr(path, "/self/task/65536/"))
		return FIXTURE_NAMESPACE_SELF_TASK;
	if (strstr(path, "/3031/"))
		return FIXTURE_NAMESPACE_FOREIGN_LEADER;
	if (strstr(path, "/self/"))
		return FIXTURE_NAMESPACE_SELF;
	return FIXTURE_NAMESPACE_NONE;
}

static const char *fixture_namespace_mountinfo_path(
	enum fixture_namespace_kind kind)
{
	switch (kind) {
	case FIXTURE_NAMESPACE_SELF:
		return "/proc/self/mountinfo";
	case FIXTURE_NAMESPACE_SELF_TASK:
		return "/proc/self/task/65536/mountinfo";
	case FIXTURE_NAMESPACE_FOREIGN_LEADER:
		return "/proc/3031/mountinfo";
	case FIXTURE_NAMESPACE_FOREIGN_TASK:
		return "/proc/3031/task/3032/mountinfo";
	default:
		return NULL;
	}
}

static dev_t fixture_namespace_default_root_device(
	enum fixture_namespace_kind kind)
{
	switch (kind) {
	case FIXTURE_NAMESPACE_SELF:
		return makedev(259U, 0U);
	case FIXTURE_NAMESPACE_SELF_TASK:
	case FIXTURE_NAMESPACE_FOREIGN_TASK:
		return makedev(259U, 10U);
	case FIXTURE_NAMESPACE_FOREIGN_LEADER:
		return makedev(259U, 9U);
	default:
		return 0;
	}
}

static uint64_t fixture_namespace_mount_id_base(
	enum fixture_namespace_kind kind)
{
	return 0x100000000ULL + ((uint64_t)kind << 20);
}

static size_t fixture_namespace_devices(
	enum fixture_namespace_kind kind, dev_t *devices, size_t capacity)
{
	const char *proc_path = fixture_namespace_mountinfo_path(kind);
	char converted[PATH_MAX];
	char line[1024];
	FILE *stream = NULL;
	size_t count = 0;

	assert(devices != NULL);
	assert(capacity > 0U);
	if (proc_path)
		stream = fopen(fixture_path(proc_path, converted), "r");
	if (stream) {
		while (count < capacity && fgets(line, sizeof(line), stream)) {
			unsigned int device_major;
			unsigned int device_minor;

			if (sscanf(line, "%*u %*u %u:%u",
				   &device_major, &device_minor) == 2)
				devices[count++] =
					makedev(device_major, device_minor);
		}
		assert(fclose(stream) == 0);
	}
	if (!count)
		devices[count++] = fixture_namespace_default_root_device(kind);
	if (fixture_hidden_namespace_kind == kind &&
	    fixture_hidden_namespace_device && count < capacity)
		devices[count++] = fixture_hidden_namespace_device;
	return count;
}

struct fixture_mount_id_request {
	uint32_t size;
	uint32_t namespace_fd;
	uint64_t mount_id;
	uint64_t parameter;
	uint64_t namespace_id;
};

struct fixture_statmount_basic {
	uint32_t size;
	uint32_t mount_options_offset;
	uint64_t mask;
	uint32_t superblock_device_major;
	uint32_t superblock_device_minor;
	uint64_t superblock_magic;
	uint32_t superblock_flags;
	uint32_t filesystem_type_offset;
	uint64_t mount_id;
	uint64_t parent_mount_id;
};

static int fixture_statx(int directory_fd, const char *path, int flags,
			 unsigned int mask, struct statx *info)
{
	enum fixture_namespace_kind kind =
		fixture_namespace_kind_for_path(path);

	if (kind != FIXTURE_NAMESPACE_NONE &&
	    fixture_path_has_suffix(path, "root")) {
		if (fixture_root_statx_error_kind == kind &&
		    fixture_root_statx_error) {
			errno = fixture_root_statx_error;
			return -1;
		}
		memset(info, 0, sizeof(*info));
		info->stx_mask = 0x00004000U;
		info->stx_mnt_id = fixture_namespace_mount_id_base(kind) + 1U;
		return 0;
	}
	return statx(directory_fd, path, flags, mask, info);
}

static long fixture_syscall(long number, ...)
{
	va_list arguments;
	long result = -1;

	va_start(arguments, number);
	if (number == SYS_statmount) {
		const struct fixture_mount_id_request *request =
			va_arg(arguments, const struct fixture_mount_id_request *);
		struct fixture_statmount_basic *status =
			va_arg(arguments, struct fixture_statmount_basic *);
		size_t status_size = va_arg(arguments, size_t);
		unsigned int flags = va_arg(arguments, unsigned int);
		enum fixture_namespace_kind kind = fixture_namespace_fd_kind;
		dev_t devices[64];
		size_t device_count;
		uint64_t base;
		uint64_t index;

		(void)flags;
		assert(request != NULL);
		assert(status != NULL);
		assert(status_size >= sizeof(*status));
		assert(request->namespace_fd == (uint32_t)fixture_namespace_fd);
		assert(kind != FIXTURE_NAMESPACE_NONE);
		if (fixture_namespace_inventory_error_kind == kind &&
		    fixture_namespace_inventory_error) {
			errno = fixture_namespace_inventory_error;
			goto out;
		}
		device_count =
			fixture_namespace_devices(kind, devices,
						 sizeof(devices) / sizeof(devices[0]));
		base = fixture_namespace_mount_id_base(kind);
		assert(request->mount_id >= base + 1U);
		index = request->mount_id - base - 1U;
		if (index >= device_count) {
			errno = ENOENT;
			goto out;
		}
		memset(status, 0, sizeof(*status));
		status->size = (uint32_t)sizeof(*status);
		status->mask = 0x00000003ULL;
		status->mount_id = request->mount_id;
		status->superblock_device_major = major(devices[index]);
		status->superblock_device_minor = minor(devices[index]);
		status->parent_mount_id =
			index == 0U ? request->mount_id : base + 1U;
		result = 0;
	} else if (number == SYS_listmount) {
		const struct fixture_mount_id_request *request =
			va_arg(arguments, const struct fixture_mount_id_request *);
		uint64_t *mount_ids = va_arg(arguments, uint64_t *);
		size_t capacity = va_arg(arguments, size_t);
		unsigned int flags = va_arg(arguments, unsigned int);
		enum fixture_namespace_kind kind = fixture_namespace_fd_kind;
		dev_t devices[64];
		size_t device_count;
		uint64_t base;
		size_t start;
		size_t written = 0;

		(void)flags;
		assert(request != NULL);
		assert(mount_ids != NULL);
		assert(request->namespace_fd == (uint32_t)fixture_namespace_fd);
		assert(kind != FIXTURE_NAMESPACE_NONE);
		if (fixture_namespace_inventory_error_kind == kind &&
		    fixture_namespace_inventory_error) {
			errno = fixture_namespace_inventory_error;
			goto out;
		}
		device_count =
			fixture_namespace_devices(kind, devices,
						 sizeof(devices) / sizeof(devices[0]));
		base = fixture_namespace_mount_id_base(kind);
		assert(request->mount_id == base + 1U);
		if (!request->parameter) {
			++fixture_namespace_inventory_scans[kind];
			start = 1U;
		} else {
			assert(request->parameter >= base + 2U);
			start = (size_t)(request->parameter - base);
		}
		while (start < device_count && written < capacity) {
			mount_ids[written++] = base + 1U + start;
			++start;
		}
		result = (long)written;
	} else {
		errno = ENOSYS;
	}
out:
	va_end(arguments);
	return result;
}

static int fixture_open(const char *path, int flags, ...)
{
	char converted[PATH_MAX];
	mode_t mode = 0;
	int fd;

	if (flags & O_CREAT) {
		va_list arguments;

		va_start(arguments, flags);
		mode = (mode_t)va_arg(arguments, int);
		va_end(arguments);
	}

	if (fixture_path_has_suffix(path, "3031/mountinfo") &&
	    fixture_peer_namespace_vanishes_on_mountinfo_open &&
	    fixture_mount_open_error) {
		char namespace_path[PATH_MAX];
		int open_error = fixture_mount_open_error;

		assert(unlink(fixture_path("/proc/3031/ns/mnt",
					   namespace_path)) == 0);
		fixture_peer_namespace_vanishes_on_mountinfo_open = 0;
		fixture_peer_namespace_vanished_on_mountinfo_open = 1;
		/* The injected leader error is one-shot; the worker stays readable. */
		fixture_mount_open_error = 0;
		errno = open_error;
		return -1;
	}
	if (fixture_path_has_suffix(path, "3031/task/3032/mountinfo") &&
	    fixture_task_mount_open_error) {
		fixture_task_mount_open_error_injected = 1;
		errno = fixture_task_mount_open_error;
		return -1;
	}
	if (fixture_other_mountinfo(path) && fixture_mount_open_error) {
		errno = fixture_mount_open_error;
		return -1;
	}
	if (!strcmp(path, "/proc/self/mountinfo") && fixture_self_mount_open_error) {
		errno = fixture_self_mount_open_error;
		return -1;
	}
	fd = open(fixture_path(path, converted), flags, mode);
	if (fd >= 0 && fixture_other_mountinfo(path)) {
		fixture_mount_fd = fd;
		fixture_mount_fd_is_peer_leader =
			strstr(path, "/3031/mountinfo") != NULL;
		fixture_peer_mountinfo_read_eof = 0;
	}
	fixture_track_task_mountinfo_open(path, fd);
	if (fd >= 0 && fixture_path_has_suffix(path, "ns/mnt")) {
		enum fixture_namespace_kind kind =
			fixture_namespace_kind_for_path(path);

		assert(kind != FIXTURE_NAMESPACE_NONE);
		assert(fixture_namespace_fd == -1);
		fixture_namespace_fd = fd;
		fixture_namespace_fd_kind = kind;
	}
	return fd;
}

static int fixture_openat(int directory_fd, const char *path, int flags, ...)
	__attribute__((unused));
static int fixture_openat(int directory_fd, const char *path, int flags, ...)
{
	char converted[PATH_MAX];
	mode_t mode = 0;
	int fd;

	if (flags & O_CREAT) {
		va_list arguments;

		va_start(arguments, flags);
		mode = (mode_t)va_arg(arguments, int);
		va_end(arguments);
	}
	if (fixture_path_has_suffix(path, "3031/task/3032/mountinfo") &&
	    fixture_task_mount_open_error) {
		fixture_task_mount_open_error_injected = 1;
		errno = fixture_task_mount_open_error;
		return -1;
	}
	if (fixture_other_mountinfo(path) && fixture_mount_open_error) {
		errno = fixture_mount_open_error;
		return -1;
	}
	if (!strcmp(path, "/proc/self/mountinfo") && fixture_self_mount_open_error) {
		errno = fixture_self_mount_open_error;
		return -1;
	}
	fd = openat(directory_fd, fixture_path(path, converted), flags, mode);
	if (fd >= 0 && fixture_other_mountinfo(path)) {
		fixture_mount_fd = fd;
		fixture_mount_fd_is_peer_leader =
			strstr(path, "/3031/mountinfo") != NULL;
		fixture_peer_mountinfo_read_eof = 0;
	}
	fixture_track_task_mountinfo_open(path, fd);
	return fd;
}

static ssize_t fixture_read(int fd, void *buffer, size_t length)
{
	ssize_t result;

	/*
	 * An opened mountinfo fd must not be treated as a harmless exited PID:
	 * losing its pathname while read(2) fails still leaves an unknown table.
	 */
	if (fd == fixture_mount_fd && fixture_mount_vanish_on_read) {
		char converted[PATH_MAX];

		fixture_mount_vanish_on_read = 0;
		assert(unlink(fixture_path("/proc/3031/mountinfo", converted)) == 0);
		assert(unlink(fixture_path("/proc/3031/ns/mnt", converted)) == 0);
		errno = ESRCH;
		return -1;
	}
	if (fd == fixture_mount_fd && fixture_mount_read_error) {
		errno = fixture_mount_read_error;
		return -1;
	}
	result = read(fd, buffer, length);
	if (fd == fixture_mount_fd && fixture_mount_fd_is_peer_leader &&
	    result == 0)
		fixture_peer_mountinfo_read_eof = 1;
	return result;
}

static struct dirent *fixture_readdir(DIR *directory)
{
	struct dirent *entry;

	/* Fail after delivering the foreign PID, not at opendir(3). */
	if (directory == fixture_proc_directory &&
	    fixture_inventory_readdir_error &&
	    fixture_inventory_seen_foreign_pid) {
		errno = fixture_inventory_readdir_error;
		return NULL;
	}
	if (directory == fixture_task_directory &&
	    fixture_task_readdir_error && fixture_task_seen_thread) {
		errno = fixture_task_readdir_error;
		return NULL;
	}
	/*
	 * Production returns to the top-level /proc iterator only after finishing
	 * the previously yielded PID, including its non-leader task scan. Require
	 * a successful read-to-EOF and close of the peer leader table so this
	 * mutation cannot accidentally fire at a task-directory EOF.
	 */
	if (directory == fixture_proc_directory &&
	    fixture_inventory_seen_foreign_pid &&
	    fixture_peer_mountinfo_after_peer_scan &&
	    fixture_peer_mountinfo_completed_reads > 0U) {
		fixture_file("3031/mountinfo",
			     fixture_peer_mountinfo_after_peer_scan);
		fixture_peer_mountinfo_after_peer_scan = NULL;
		fixture_peer_mountinfo_after_peer_scan_injected = 1;
	}
	entry = readdir(directory);
	if (entry && directory == fixture_task_directory &&
	    !strcmp(entry->d_name, "3032"))
		fixture_task_seen_thread = 1;
	if (entry && !strcmp(entry->d_name, "3031")) {
		fixture_inventory_seen_foreign_pid = 1;
		if (fixture_peer_mountinfo_before_peer_scan) {
			fixture_file("3031/mountinfo",
				     fixture_peer_mountinfo_before_peer_scan);
			fixture_peer_mountinfo_before_peer_scan = NULL;
			fixture_peer_mountinfo_before_peer_scan_injected = 1;
		}
		if (fixture_mount_open_error_before_peer_scan) {
			fixture_mount_open_error =
				fixture_mount_open_error_before_peer_scan;
			fixture_mount_open_error_before_peer_scan = 0;
			fixture_mount_open_error_before_peer_scan_injected = 1;
		}
		/*
		 * Reproduce a mount racing the already-read self snapshot while the
		 * foreign PID is still provably in the same mount namespace. Both
		 * synthetic views change because a real same-namespace mount is shared.
		 */
		if (fixture_same_namespace_mount_after_self_snapshot) {
			fixture_file("self/mountinfo",
				     "36 25 8:4 / / rw - ext4 /dev/root-sibling rw\n"
				     "37 36 8:1 /subtree /selected-bind rw - ext4 /dev/selected rw\n");
			fixture_file("3031/mountinfo",
				     "36 25 8:4 / / rw - ext4 /dev/root-sibling rw\n"
				     "37 36 8:1 /subtree /selected-bind rw - ext4 /dev/selected rw\n");
			fixture_same_namespace_mount_after_self_snapshot = 0;
			fixture_same_namespace_mount_injected = 1;
		}
	}
	return entry;
}

static int fixture_close(int fd)
{
	int is_remote = fd == fixture_mount_fd;
	int is_coordinator_task = fd == fixture_coordinator_task_mount_fd;
	int is_namespace = fd == fixture_namespace_fd;
	int peer_leader_read_complete =
		is_remote && fixture_mount_fd_is_peer_leader &&
		fixture_peer_mountinfo_read_eof;
	int result;

	if (is_remote) {
		fixture_mount_fd = -1;
		fixture_mount_fd_is_peer_leader = 0;
		fixture_peer_mountinfo_read_eof = 0;
	}
	result = close(fd);
	if (result < 0)
		return result;
	if (is_coordinator_task)
		fixture_coordinator_task_mount_fd = -1;
	if (is_namespace) {
		fixture_namespace_fd = -1;
		fixture_namespace_fd_kind = FIXTURE_NAMESPACE_NONE;
	}
	if (is_remote && fixture_mount_close_error) {
		errno = fixture_mount_close_error;
		return -1;
	}
	if (peer_leader_read_complete)
		++fixture_peer_mountinfo_completed_reads;
	return 0;
}

static FILE *fixture_fopen(const char *path, const char *mode)
	__attribute__((unused));
static FILE *fixture_fopen(const char *path, const char *mode)
{
	char converted[PATH_MAX];

	if (fixture_path_has_suffix(path, "3031/task/3032/mountinfo") &&
	    fixture_task_mount_open_error) {
		fixture_task_mount_open_error_injected = 1;
		errno = fixture_task_mount_open_error;
		return NULL;
	}
	if (fixture_other_mountinfo(path) && fixture_mount_open_error) {
		errno = fixture_mount_open_error;
		return NULL;
	}
	if (!strcmp(path, "/proc/self/mountinfo") && fixture_self_mount_open_error) {
		errno = fixture_self_mount_open_error;
		return NULL;
	}
	return fopen(fixture_path(path, converted), mode);
}

static DIR *fixture_opendir(const char *path)
{
	char converted[PATH_MAX];
	DIR *directory;

	if (!strcmp(path, "/proc") && fixture_inventory_error) {
		errno = fixture_inventory_error;
		return NULL;
	}
	directory = opendir(fixture_path(path, converted));
	if (directory && !strcmp(path, "/proc"))
		fixture_proc_directory = directory;
	if (directory && strstr(path, "/task")) {
		fixture_task_directory = directory;
		fixture_task_seen_thread = 0;
	}
	return directory;
}

static int fixture_stat(const char *path, struct stat *info)
	__attribute__((unused));
static int fixture_stat(const char *path, struct stat *info)
{
	char converted[PATH_MAX];

	/* Model a TID reused with a different mount namespace between two stats. */
	if (strstr(path, "/3031/task/3032/ns/mnt") &&
	    fixture_task_namespace_reuse_on_stat) {
		char retired_namespace_path[PATH_MAX];
		int path_length;
		int result = stat(fixture_path(path, converted), info);

		if (result < 0)
			return result;
		path_length = snprintf(retired_namespace_path,
				       sizeof(retired_namespace_path),
				       "%s/3031/task/3032/ns/mnt.retired",
				       fixture_proc_root);
		assert(path_length > 0 &&
		       (size_t)path_length < sizeof(retired_namespace_path));
		assert(rename(converted, retired_namespace_path) == 0);
		fixture_file("3031/task/3032/ns/mnt",
			     "reused TID mount namespace\n");
		fixture_task_namespace_reuse_on_stat = 0;
		fixture_task_namespace_reuse_injected = 1;
		return result;
	}
	if ((strstr(path, "/3031/ns/mnt") ||
	     strstr(path, "/3031/task/3032/ns/mnt")) &&
	    fixture_namespace_stat_error) {
		errno = fixture_namespace_stat_error;
		return -1;
	}
	if (strstr(path, "/3031/ns/mnt") &&
	    fixture_peer_namespace_vanishes_between_stats) {
		int result = stat(fixture_path(path, converted), info);

		if (result == 0) {
			assert(unlink(converted) == 0);
			fixture_peer_namespace_vanishes_between_stats = 0;
			fixture_peer_namespace_vanished_between_stats = 1;
		}
		return result;
	}
	if (strstr(path, "/3031/ns/mnt") &&
	    fixture_peer_namespace_changes_between_stats) {
		/*
		 * Capture the old shared inode for the first production stat, then
		 * switch both namespace identity and mount table before production
		 * performs its confirming stat. This keeps the synthetic procfs view
		 * coherent across the modeled process mount-namespace transition.
		 */
		int result = stat(fixture_path(path, converted), info);

		if (result == 0) {
			assert(fixture_peer_mountinfo_after_namespace_change != NULL);
			assert(unlink(converted) == 0);
			fixture_file("3031/ns/mnt", "changed foreign namespace\n");
			fixture_file("3031/mountinfo",
				     fixture_peer_mountinfo_after_namespace_change);
			fixture_peer_mountinfo_after_namespace_change = NULL;
			fixture_peer_namespace_changes_between_stats = 0;
			fixture_peer_namespace_changed = 1;
		}
		return result;
	}
	if (fixture_regular_swap_path &&
	    !strcmp(path, fixture_regular_swap_path)) {
		memset(info, 0, sizeof(*info));
		info->st_mode = S_IFREG | 0600;
		info->st_dev = fixture_regular_swap_device;
		info->st_nlink = 1;
		return 0;
	}
	return stat(fixture_path(path, converted), info);
}

static int fixture_lstat(const char *path, struct stat *info)
	__attribute__((unused));
static int fixture_lstat(const char *path, struct stat *info)
{
	char converted[PATH_MAX];

	return lstat(fixture_path(path, converted), info);
}

static ssize_t fixture_readlink(const char *path, char *buffer, size_t size)
{
	size_t length;

	if (strcmp(path, "/proc/self/root"))
		return readlink(path, buffer, size);
	length = strlen(fixture_self_root);
	if (length > size)
		length = size;
	memcpy(buffer, fixture_self_root, length);
	return (ssize_t)length;
}

#define open(...) fixture_open(__VA_ARGS__)
#define openat(...) fixture_openat(__VA_ARGS__)
#define read(...) fixture_read(__VA_ARGS__)
#define close(...) fixture_close(__VA_ARGS__)
#define fopen(...) fixture_fopen(__VA_ARGS__)
#define opendir(...) fixture_opendir(__VA_ARGS__)
#define readdir(...) fixture_readdir(__VA_ARGS__)
#define stat(...) fixture_stat(__VA_ARGS__)
#define lstat(...) fixture_lstat(__VA_ARGS__)
#define readlink(...) fixture_readlink(__VA_ARGS__)
#define statx(...) fixture_statx(__VA_ARGS__)
#define syscall(...) fixture_syscall(__VA_ARGS__)
/* Keep the synthetic foreign PID distinct from the production reader's self. */
#define getpid() ((pid_t)65535)
#define main swapz_primary_program_main
#include "../../../../src/userspace/swapz-primary.c"
#undef main
#undef getpid
#undef syscall
#undef statx
#undef lstat
#undef stat
#undef readlink
#undef readdir
#undef opendir
#undef fopen
#undef close
#undef read
#undef openat
#undef open

static void fixture_file(const char *relative, const char *contents)
{
	char path[PATH_MAX];
	FILE *stream;
	int length = snprintf(path, sizeof(path), "%s/%s", fixture_proc_root,
			      relative);

	assert(length > 0 && (size_t)length < sizeof(path));
	stream = fopen(path, "w");
	assert(stream != NULL);
	assert(fputs(contents, stream) >= 0);
	assert(fclose(stream) == 0);
}


static void fixture_bytes(const char *relative, const void *contents,
			  size_t contents_length)
{
	char path[PATH_MAX];
	FILE *stream;
	int length = snprintf(path, sizeof(path), "%s/%s", fixture_proc_root,
			      relative);

	assert(length > 0 && (size_t)length < sizeof(path));
	stream = fopen(path, "wb");
	assert(stream != NULL);
	assert(fwrite(contents, 1U, contents_length, stream) == contents_length);
	assert(fclose(stream) == 0);
}

/* Exceed the production per-table cap with bounded, fixed-size writes. */
static void fixture_oversized_file(const char *relative)
{
	char path[PATH_MAX];
	char buffer[256];
	FILE *stream;
	size_t index;
	int length = snprintf(path, sizeof(path), "%s/%s",
			      fixture_proc_root, relative);

	assert(length > 0 && (size_t)length < sizeof(path));
	stream = fopen(path, "wb");
	assert(stream != NULL);
	memset(buffer, 'X', sizeof(buffer));
	for (index = 0; index <= SWAPZ_PRIMARY_MOUNTINFO_BUFFER_BYTES /
				     sizeof(buffer); ++index)
		assert(fwrite(buffer, 1U, sizeof(buffer), stream) == sizeof(buffer));
	assert(fclose(stream) == 0);
}

static void fixture_unlink(const char *relative)
{
	char path[PATH_MAX];
	int length = snprintf(path, sizeof(path), "%s/%s", fixture_proc_root,
			      relative);

	assert(length > 0 && (size_t)length < sizeof(path));
	assert(unlink(path) == 0);
}

static void fixture_unlink_if_present(const char *relative)
{
	char path[PATH_MAX];
	int length = snprintf(path, sizeof(path), "%s/%s", fixture_proc_root,
			      relative);

	assert(length > 0 && (size_t)length < sizeof(path));
	if (unlink(path) < 0)
		assert(errno == ENOENT);
}

static void fixture_share_mount_namespace(void)
{
	char self_namespace[PATH_MAX];
	char pid_namespace[PATH_MAX];
	int length;

	fixture_unlink("3031/ns/mnt");
	length = snprintf(self_namespace, sizeof(self_namespace),
			  "%s/self/ns/mnt", fixture_proc_root);
	assert(length > 0 && (size_t)length < sizeof(self_namespace));
	length = snprintf(pid_namespace, sizeof(pid_namespace),
			  "%s/3031/ns/mnt", fixture_proc_root);
	assert(length > 0 && (size_t)length < sizeof(pid_namespace));
	assert(link(self_namespace, pid_namespace) == 0);
}

static void fixture_reset(void)
{
	fixture_mount_open_error = 0;
	fixture_task_mount_open_error = 0;
	fixture_task_mount_open_error_injected = 0;
	fixture_self_mount_open_error = 0;
	fixture_inventory_error = 0;
	fixture_inventory_readdir_error = 0;
	fixture_inventory_seen_foreign_pid = 0;
	fixture_task_readdir_error = 0;
	fixture_task_seen_thread = 0;
	fixture_task_namespace_reuse_on_stat = 0;
	fixture_task_namespace_reuse_injected = 0;
	fixture_coordinator_task_mountinfo_opens = 0U;
	fixture_foreign_task_mountinfo_opens = 0U;
	fixture_coordinator_task_mount_fd = -1;
	fixture_proc_directory = NULL;
	fixture_task_directory = NULL;
	fixture_same_namespace_mount_after_self_snapshot = 0;
	fixture_same_namespace_mount_injected = 0;
	fixture_peer_mountinfo_before_peer_scan = NULL;
	fixture_peer_mountinfo_before_peer_scan_injected = 0;
	fixture_mount_open_error_before_peer_scan = 0;
	fixture_mount_open_error_before_peer_scan_injected = 0;
	fixture_peer_mountinfo_after_peer_scan = NULL;
	fixture_peer_mountinfo_after_peer_scan_injected = 0;
	fixture_peer_namespace_changes_between_stats = 0;
	fixture_peer_namespace_changed = 0;
	fixture_peer_namespace_vanishes_between_stats = 0;
	fixture_peer_namespace_vanished_between_stats = 0;
	fixture_peer_namespace_vanishes_on_mountinfo_open = 0;
	fixture_peer_namespace_vanished_on_mountinfo_open = 0;
	fixture_peer_mountinfo_after_namespace_change = NULL;
	fixture_mount_vanish_on_read = 0;
	fixture_namespace_stat_error = 0;
	fixture_mount_read_error = 0;
	fixture_mount_close_error = 0;
	fixture_mount_fd = -1;
	fixture_mount_fd_is_peer_leader = 0;
	fixture_peer_mountinfo_read_eof = 0;
	fixture_peer_mountinfo_completed_reads = 0U;
	fixture_regular_swap_path = NULL;
	fixture_regular_swap_device = 0;
	strcpy(fixture_self_root, "/");
	fixture_namespace_fd = -1;
	fixture_namespace_fd_kind = FIXTURE_NAMESPACE_NONE;
	fixture_hidden_namespace_kind = FIXTURE_NAMESPACE_NONE;
	fixture_hidden_namespace_device = 0;
	fixture_namespace_inventory_error_kind = FIXTURE_NAMESPACE_NONE;
	fixture_namespace_inventory_error = 0;
	fixture_root_statx_error_kind = FIXTURE_NAMESPACE_NONE;
	fixture_root_statx_error = 0;
	memset(fixture_namespace_inventory_scans, 0,
	       sizeof(fixture_namespace_inventory_scans));
	fixture_unlink_if_present("self/ns/mnt");
	fixture_unlink_if_present("3031/ns/mnt");
	fixture_file("self/ns/mnt", "coordinator mount namespace\n");
	fixture_file("3031/ns/mnt", "foreign mount namespace\n");
	fixture_file("self/mountinfo",
		     "36 25 259:0 / / rw - ext4 /dev/root rw\n");
	fixture_file("3031/mountinfo",
		     "36 25 259:9 / / rw - ext4 /dev/other-root rw\n");
	fixture_file("3031/ns/mnt", "mount namespace still present\n");
}

static unsigned int fixture_failures;

/* expected_errno == 0 means a parsed inventory; in that case a mounted
 * target refuses through target_mounted rather than an errno value. */
static void expect_mount_identity_admission(
	const char *case_name, dev_t expected_root_device, dev_t parent_device,
	int should_allow, int expected_errno, const char *safety_gate)
{
	struct swapz_primary_mount_facts facts = {0};
	int result;
	int allowed;

	errno = 0;
	result = swapz_primary_read_mount_facts(&facts, parent_device);
	allowed = result == 0 && !facts.target_mounted;
	if (allowed != should_allow ||
	    (expected_errno ? (result == 0 || errno != expected_errno) :
			      result != 0) ||
	    (result == 0 && (!facts.root_mount_seen ||
			    facts.root_device != expected_root_device))) {
		fprintf(stderr, "FAIL: %s: gate=%s result=%d errno=%d target=%d "
			"root_seen=%d root=%u:%u expected_root=%u:%u "
			"target_parent=%u:%u (expected %s)\n",
			case_name, safety_gate, result, errno, facts.target_mounted,
			facts.root_mount_seen, major(facts.root_device),
			minor(facts.root_device), major(expected_root_device),
			minor(expected_root_device), major(parent_device),
			minor(parent_device),
			should_allow ? "admitted" : "refused");
		/* This fixture only calls the read-only production mount reader. */
		fprintf(stderr,
			"FAIL: phase=mount-admission case=%s expected=%s "
			"actual_result=%d observed_errno=%d "
			"header_write=NOT_INTERCEPTED mapper=NOT_INTERCEPTED "
			"mkswap=NOT_INTERCEPTED swapon=NOT_INTERCEPTED "
			"limitation=reader-only-procfs-snapshot "
			"safe_action=retain_inactive_target\n",
			case_name, should_allow ? "admitted" : "refused",
			result, errno);
		++fixture_failures;
	}
	if (fixture_mount_fd != -1) {
		fprintf(stderr,
			"FAIL: phase=descriptor-closure case=%s "
			"expected=closed foreign mountinfo descriptor actual_fd=%d "
			"observed_errno=%d header_write=NOT_INTERCEPTED "
			"mapper=NOT_INTERCEPTED mkswap=NOT_INTERCEPTED "
			"swapon=NOT_INTERCEPTED limitation=reader-only-procfs-snapshot "
			"safe_action=retain_inactive_target gate=%s\n",
			case_name, fixture_mount_fd, errno, safety_gate);
		++fixture_failures;
		(void)close(fixture_mount_fd);
		fixture_mount_fd = -1;
	}
	if (fixture_namespace_fd != -1) {
		fprintf(stderr,
			"FAIL: phase=descriptor-closure case=%s "
			"expected=closed pinned namespace descriptor actual_fd=%d "
			"observed_errno=%d header_write=NOT_INTERCEPTED "
			"mapper=NOT_INTERCEPTED mkswap=NOT_INTERCEPTED "
			"swapon=NOT_INTERCEPTED limitation=reader-only-procfs-snapshot "
			"safe_action=retain_inactive_target gate=%s\n",
			case_name, fixture_namespace_fd, errno, safety_gate);
		++fixture_failures;
		(void)close(fixture_namespace_fd);
		fixture_namespace_fd = -1;
		fixture_namespace_fd_kind = FIXTURE_NAMESPACE_NONE;
	}
	if (fixture_coordinator_task_mount_fd != -1) {
		fprintf(stderr,
			"FAIL: phase=descriptor-closure case=%s "
			"expected=closed coordinator non-leader mountinfo descriptor "
			"actual_fd=%d observed_errno=%d header_write=NOT_INTERCEPTED "
			"mapper=NOT_INTERCEPTED mkswap=NOT_INTERCEPTED "
			"swapon=NOT_INTERCEPTED limitation=reader-only-procfs-snapshot "
			"safe_action=retain_inactive_target gate=%s\n",
			case_name, fixture_coordinator_task_mount_fd, errno,
			safety_gate);
		++fixture_failures;
		(void)close(fixture_coordinator_task_mount_fd);
		fixture_coordinator_task_mount_fd = -1;
	}
}

static void expect_task_mountinfo_open_count(
	const char *case_name, unsigned int actual_count,
	unsigned int expected_count)
{
	if (actual_count == expected_count)
		return;
	fprintf(stderr,
		"FAIL: phase=task-mountinfo-attribution case=%s "
		"expected_opens=%u actual_opens=%u observed_errno=%d "
		"header_write=NOT_INTERCEPTED mapper=NOT_INTERCEPTED "
		"mkswap=NOT_INTERCEPTED swapon=NOT_INTERCEPTED "
		"limitation=reader-only-procfs-snapshot "
		"safe_action=retain_inactive_target\n",
		case_name, expected_count, actual_count, errno);
	++fixture_failures;
}

static void expect_nonleader_bound_refusal(
	const char *case_name, size_t visible_task_count, size_t total_bytes,
	unsigned int expected_task_opens)
{
	struct swapz_primary_mount_facts facts = {0};
	struct stat self_namespace_info;
	int result;

	assert(fixture_stat("/proc/self/ns/mnt", &self_namespace_info) == 0);
	fixture_foreign_task_mountinfo_opens = 0U;
	errno = 0;
	result = swapz_primary_read_nonleader_mount_facts(
		"/proc/3031/task", "/proc/3031/ns/mnt", "3031", 0,
		makedev(8U, 0U), &self_namespace_info, 0, &facts,
		&visible_task_count, &total_bytes);
	if (result == 0 || errno != EOVERFLOW) {
		fprintf(stderr,
			"FAIL: phase=task-bound case=%s expected=EOVERFLOW refusal "
			"actual_result=%d observed_errno=%d "
			"header_write=NOT_INTERCEPTED mapper=NOT_INTERCEPTED "
			"mkswap=NOT_INTERCEPTED swapon=NOT_INTERCEPTED "
			"limitation=reader-only-procfs-snapshot "
			"safe_action=retain_inactive_target\n",
			case_name, result, errno);
		++fixture_failures;
	}
	expect_task_mountinfo_open_count(
		case_name, fixture_foreign_task_mountinfo_opens,
		expected_task_opens);
	if (fixture_mount_fd != -1) {
		fprintf(stderr,
			"FAIL: phase=descriptor-closure case=%s "
			"expected=closed bounded-task mountinfo descriptor actual_fd=%d "
			"observed_errno=%d header_write=NOT_INTERCEPTED "
			"mapper=NOT_INTERCEPTED mkswap=NOT_INTERCEPTED "
			"swapon=NOT_INTERCEPTED limitation=reader-only-procfs-snapshot "
			"safe_action=retain_inactive_target\n",
			case_name, fixture_mount_fd, errno);
		++fixture_failures;
		(void)close(fixture_mount_fd);
		fixture_mount_fd = -1;
	}
}


/*
 * A disappearing leader namespace marker does not establish that all of its
 * sibling tasks exited. A surviving task may hold a different mount namespace
 * with the selected partition or its parent mounted. The inventory must
 * report a busy target or fail closed; a clean admission is never sufficient.
 * This is a synthetic procfs identity check, not a loaded-host namespace claim.
 */
enum fixture_leader_namespace_loss_timing {
	FIXTURE_LEADER_NAMESPACE_ABSENT_BEFORE_SCAN,
	FIXTURE_LEADER_NAMESPACE_LOST_DURING_CONFIRMATION,
	FIXTURE_LEADER_NAMESPACE_LOST_ON_MOUNTINFO_OPEN,
};

static void expect_surviving_task_with_missing_leader_namespace(
	const char *case_name, const char *task_mountinfo,
	enum fixture_leader_namespace_loss_timing timing)
{
	struct swapz_primary_mount_facts facts = {0};
	const dev_t expected_root = makedev(259U, 0U);
	const char *identity_class = NULL;
	int result;
	int first_errno;
	int timing_injected = 1;

	fixture_reset();
	/* Recreate the worker marker so this regression never depends on test order. */
	fixture_unlink_if_present("3031/task/3032/ns/mnt");
	fixture_file("3031/task/3032/ns/mnt",
		     "surviving non-leader mount namespace\n");
	fixture_file("3031/task/3032/mountinfo", task_mountinfo);
	switch (timing) {
	case FIXTURE_LEADER_NAMESPACE_ABSENT_BEFORE_SCAN:
		identity_class = "leader-marker-absent-live-worker";
		fixture_unlink("3031/ns/mnt");
		break;
	case FIXTURE_LEADER_NAMESPACE_LOST_DURING_CONFIRMATION:
		identity_class = "leader-marker-lost-during-confirmation-live-worker";
		fixture_share_mount_namespace();
		fixture_peer_namespace_vanishes_between_stats = 1;
		break;
	case FIXTURE_LEADER_NAMESPACE_LOST_ON_MOUNTINFO_OPEN:
		identity_class = "leader-marker-lost-after-mountinfo-open-error-live-worker";
		fixture_mount_open_error = ENOENT;
		fixture_peer_namespace_vanishes_on_mountinfo_open = 1;
		break;
	default:
		assert(0 && "invalid leader namespace loss timing");
	}

	errno = 0;
	result = swapz_primary_read_mount_facts(&facts, makedev(8U, 0U));
	first_errno = errno;
	if (timing == FIXTURE_LEADER_NAMESPACE_LOST_DURING_CONFIRMATION)
		timing_injected = fixture_peer_namespace_vanished_between_stats;
	else if (timing == FIXTURE_LEADER_NAMESPACE_LOST_ON_MOUNTINFO_OPEN)
		timing_injected = fixture_peer_namespace_vanished_on_mountinfo_open;

	if (!timing_injected) {
		fprintf(stderr,
			"FAIL: phase=foreign-leader-namespace-inventory case=%s "
			"identity_class=%s expected=timed-identity-loss "
			"observed=injection-not-run original_errno=%d "
			"safe_retry=complete-fresh-task-inventory\n",
			case_name, identity_class, result < 0 ? first_errno : 0);
		++fixture_failures;
	}
	if (result == 0 && !facts.target_mounted) {
		fprintf(stderr,
			"FAIL: phase=foreign-leader-namespace-inventory case=%s "
			"identity_class=%s expected=BUSY-or-BLOCKED observed=ADMITTED "
			"observed_task_mountinfo_opens=%u original_errno=none "
			"safe_retry=complete-fresh-task-inventory "
			"header_write=NOT_INTERCEPTED mapper=NOT_INTERCEPTED "
			"mkswap=NOT_INTERCEPTED swapon=NOT_INTERCEPTED\n",
			case_name, identity_class,
			fixture_foreign_task_mountinfo_opens);
		++fixture_failures;
	}
	/*
	 * These cases deliberately keep the worker namespace and mountinfo readable.
	 * A generic early refusal at the vanished leader is safe but does not prove
	 * the production scanner inspected the surviving task as required.
	 */
	if (fixture_foreign_task_mountinfo_opens != 1U) {
		fprintf(stderr,
			"FAIL: phase=foreign-leader-namespace-inventory case=%s "
			"identity_class=task-attribution-missing "
			"expected_task_mountinfo_opens=1 observed_task_mountinfo_opens=%u "
			"original_errno=%d safe_retry=complete-fresh-task-inventory\n",
			case_name, fixture_foreign_task_mountinfo_opens,
			result < 0 ? first_errno : 0);
		++fixture_failures;
	}
	if (result < 0 && first_errno == 0) {
		fprintf(stderr,
			"FAIL: phase=foreign-leader-namespace-inventory case=%s "
			"identity_class=unattributed-refusal "
			"expected=preserved-error observed=missing-errno "
			"original_errno=0 safe_retry=complete-fresh-task-inventory\n",
			case_name);
		++fixture_failures;
	}
	if (result == 0 &&
	    (!facts.root_mount_seen || facts.root_device != expected_root)) {
		fprintf(stderr,
			"FAIL: phase=foreign-leader-namespace-inventory case=%s "
			"identity_class=coordinator-root-changed "
			"expected=original-root-preserved observed=mismatched-root "
			"original_errno=none safe_retry=complete-fresh-task-inventory\n",
			case_name);
		++fixture_failures;
	}
	if (fixture_mount_fd != -1 || fixture_coordinator_task_mount_fd != -1) {
		fprintf(stderr,
			"FAIL: phase=foreign-leader-namespace-inventory case=%s "
			"identity_class=descriptor-lifetime "
			"expected=all-mountinfo-fds-closed observed=open-fd "
			"original_errno=%d safe_retry=close-owned-fds-and-rescan\n",
			case_name, result < 0 ? first_errno : 0);
		++fixture_failures;
		if (fixture_mount_fd != -1) {
			(void)close(fixture_mount_fd);
			fixture_mount_fd = -1;
		}
		if (fixture_coordinator_task_mount_fd != -1) {
			(void)close(fixture_coordinator_task_mount_fd);
			fixture_coordinator_task_mount_fd = -1;
		}
	}
}

/* Keep the original controls anchored to their original synthetic identities. */
static void expect_mount_admission(const char *case_name, int should_allow,
				   int expected_errno)
{
	expect_mount_identity_admission(
		case_name, makedev(259U, 0U), makedev(8U, 0U),
		should_allow, expected_errno, "selected target/sibling/root/namespace");
}

/*
 * The synthetic root 8:4 and selected target 8:1 model different partitions
 * whose independently verified physical parent would be 8:0. This fixture
 * checks production mount admission, not a real sysfs ancestry resolution or
 * an accepted host-bound shared-root scope record.
 */
static void fixture_same_parent_root(void)
{
	fixture_reset();
	fixture_file("self/mountinfo",
		     "36 25 8:4 / / rw - ext4 /dev/root-sibling rw\n");
}

static void test_shared_root_parent_mount_gates(void)
{
	const dev_t root_device = makedev(8U, 4U);
	const dev_t target_parent = makedev(8U, 0U);
	const dev_t changed_parent = makedev(8U, 8U);

	fixture_same_parent_root();
	expect_mount_identity_admission("shared-parent clean root sibling",
					root_device, target_parent, 1, 0,
					"sibling/root");
	fixture_file("3031/mountinfo",
		     "36 25 259:9 / / rw - ext4 /dev/foreign-root rw\n"
		     "37 36 8:2 / /sibling rw - ext4 /dev/sibling rw\n");
	expect_mount_identity_admission("shared-parent unrelated foreign sibling",
					root_device, target_parent, 1, 0,
					"sibling/root");

	/* The mountinfo major:minor, not its /dev source label, identifies a bind. */
	fixture_same_parent_root();
	fixture_file("self/mountinfo",
		     "36 25 8:4 / / rw - ext4 /dev/root-sibling rw\n"
		     "37 36 8:1 /subtree /selected-bind rw - ext4 /dev/unrelated rw\n");
	expect_mount_identity_admission("shared-parent local selected bind",
					root_device, target_parent, 0, 0,
					"selected target");
	fixture_same_parent_root();
	fixture_file("3031/mountinfo",
		     "36 25 259:9 / / rw - ext4 /dev/foreign-root rw\n"
		     "37 36 8:2 / /sibling rw - ext4 /dev/sibling rw\n"
		     "38 36 8:1 /subtree /selected-bind rw - ext4 /dev/unrelated rw\n");
	expect_mount_identity_admission("shared-parent foreign selected bind",
					root_device, target_parent, 0, 0,
					"selected target/cross-namespace");
	fixture_same_parent_root();
	fixture_file("3031/mountinfo",
		     "36 25 8:1 / / rw - ext4 /dev/foreign-root rw\n");
	expect_mount_identity_admission("shared-parent foreign root is selected",
					root_device, target_parent, 0, 0,
					"selected target/cross-namespace");
	fixture_same_parent_root();
	fixture_file("self/mountinfo",
		     "36 25 8:1 / / rw - ext4 /dev/root-alias rw\n");
	expect_mount_identity_admission("selected target masquerades as local root",
					makedev(8U, 1U), target_parent, 0, 0,
					"selected target/root");
	fixture_same_parent_root();
	fixture_file("3031/mountinfo",
		     "36 25 259:9 / / rw - ext4 /dev/foreign-root rw\n"
		     "37 36 8:0 / /mounted-parent rw - ext4 /dev/not-parent rw\n");
	expect_mount_identity_admission("shared-parent foreign parent mount",
					root_device, target_parent, 0, 0,
					"device ancestry/cross-namespace");

	/* The same-parent relationship never waives a complete PID inventory. */
	fixture_same_parent_root();
	fixture_file("3031/mountinfo", "malformed\n");
	expect_mount_identity_admission("shared-parent unresolved remote identity",
					root_device, target_parent, 0, EINVAL,
					"unresolved identity");
	fixture_same_parent_root();
	fixture_mount_open_error = EACCES;
	expect_mount_identity_admission("shared-parent unreadable foreign namespace",
					root_device, target_parent, 0, EACCES,
					"namespace enumeration");
	fixture_same_parent_root();
	fixture_inventory_readdir_error = EIO;
	expect_mount_identity_admission("shared-parent incomplete PID enumeration",
					root_device, target_parent, 0, EIO,
					"namespace enumeration");
	fixture_same_parent_root();
	fixture_share_mount_namespace();
	fixture_file("3031/mountinfo", "");
	expect_mount_identity_admission("shared-parent complete same-namespace view",
					root_device, target_parent, 1, 0,
					"sibling/root");
	fixture_file("self/mountinfo",
		     "36 25 8:4 / / rw - ext4 /dev/root-sibling rw\n"
		     "37 36 8:1 /subtree /selected-bind rw - ext4 /dev/unrelated rw\n");
	expect_mount_identity_admission("shared-parent same-namespace skip keeps target",
					root_device, target_parent, 0, 0,
					"selected target/namespace identity");

	/*
	 * A mount reader cannot invent a parent-device identity. Its stale-parent
	 * snapshot is intentionally a positive control, NOT coordinator admission:
	 * the caller must re-resolve and compare ancestry before mutation.
	 */
	fixture_same_parent_root();
	fixture_file("3031/mountinfo",
		     "36 25 259:9 / / rw - ext4 /dev/foreign-root rw\n"
		     "37 36 8:8 / /changed-parent rw - ext4 /dev/other rw\n");
	expect_mount_identity_admission("stale parent argument alone misses new parent",
					root_device, target_parent, 1, 0,
					"device ancestry (caller must revalidate)");
	expect_mount_identity_admission("re-resolved parent mount must refuse",
					root_device, changed_parent, 0, 0,
					"device ancestry/cross-namespace");
}


static void probe_shared_root_parent_same_namespace_snapshot_gap(void)
{
	const dev_t root_device = makedev(8U, 4U);
	const dev_t target_parent = makedev(8U, 0U);
	struct swapz_primary_mount_facts facts = {0};
	int result;
	int observed_errno;

	fixture_same_parent_root();
	fixture_share_mount_namespace();
	/*
	 * Production has already consumed self/mountinfo when readdir(3) yields
	 * PID 3031. Injecting here models a selected-target mount created in that
	 * shared namespace before the shortcut's two identity checks and skip.
	 */
	fixture_same_namespace_mount_after_self_snapshot = 1;
	errno = 0;
	result = swapz_primary_read_mount_facts(&facts, target_parent);
	observed_errno = errno;
	if (!fixture_same_namespace_mount_injected) {
		fprintf(stderr,
			"FAIL: boundary=self-post-snapshot case=selected "
			"reason=injection-not-run result=%d observed_errno=%d target=%d "
			"header_write=NOT_INTERCEPTED mapper=NOT_INTERCEPTED "
			"mkswap=NOT_INTERCEPTED swapon=NOT_INTERCEPTED "
			"limitation=reader-only-procfs-snapshot\n",
			result, observed_errno, facts.target_mounted);
		++fixture_failures;
		return;
	}
	if (fixture_mount_fd != -1) {
		fprintf(stderr,
			"FAIL: boundary=self-post-snapshot case=selected "
			"reason=mountinfo-fd-leak result=%d observed_errno=%d target=%d "
			"header_write=NOT_INTERCEPTED mapper=NOT_INTERCEPTED "
			"mkswap=NOT_INTERCEPTED swapon=NOT_INTERCEPTED "
			"limitation=reader-only-procfs-snapshot\n",
			result, observed_errno, facts.target_mounted);
		++fixture_failures;
		(void)close(fixture_mount_fd);
		fixture_mount_fd = -1;
	}
	if (result == 0 &&
	    (!facts.root_mount_seen || facts.root_device != root_device)) {
		fprintf(stderr,
			"FAIL: boundary=self-post-snapshot case=selected "
			"reason=root-identity result=%d observed_errno=%d target=%d "
			"root_seen=%d root=%u:%u expected_root=%u:%u "
			"header_write=NOT_INTERCEPTED mapper=NOT_INTERCEPTED "
			"mkswap=NOT_INTERCEPTED swapon=NOT_INTERCEPTED "
			"limitation=reader-only-procfs-snapshot\n",
			result, observed_errno, facts.target_mounted,
			facts.root_mount_seen, major(facts.root_device),
			minor(facts.root_device), major(root_device),
			minor(root_device));
		++fixture_failures;
		return;
	}
	if (result == 0 && !facts.target_mounted) {
		/*
		 * Do not turn a known non-atomic snapshot gap into a passing safety
		 * claim. A future production fix may instead report target_mounted or
		 * fail closed; either outcome safely retires this UNPROVEN observation.
		 */
		printf("UNPROVEN: boundary=self-post-snapshot case=selected "
		       "result=0 errno=%d target=0 prevented=none "
		       "header_write=NOT_INTERCEPTED mapper=NOT_INTERCEPTED "
		       "mkswap=NOT_INTERCEPTED swapon=NOT_INTERCEPTED "
		       "limitation=reader-only-procfs-snapshot-cannot-prove-kernel-exclusion\n",
		       observed_errno);
	}
}


/* Assert that every timing control actually fired inside the production scan. */
static void fixture_expect_timed_change(const char *case_name, int injected)
{
	if (!injected) {
		fprintf(stderr, "FAIL: %s: gate=timed procfs injection did not run\n",
			case_name);
		++fixture_failures;
	}
}

static void test_controlled_mount_snapshot_timings(void)
{
	static const char foreign_selected_mount[] =
		"36 25 259:9 / / rw - ext4 /dev/foreign-root rw\n"
		"37 36 8:1 / /selected rw - ext4 /dev/selected rw\n";
	static const char foreign_parent_mount[] =
		"36 25 259:9 / / rw - ext4 /dev/foreign-root rw\n"
		"37 36 8:0 / /parent rw - ext4 /dev/not-parent rw\n";
	static const char foreign_selected_bind_mount[] =
		"36 25 259:9 / / rw - ext4 /dev/foreign-root rw\n"
		"37 36 8:1 /subtree /selected-bind rw - ext4 /dev/not-selected rw\n";
	static const char foreign_changed_parent_mount[] =
		"36 25 259:9 / / rw - ext4 /dev/foreign-root rw\n"
		"37 36 8:8 / /changed-parent rw - ext4 /dev/other rw\n";
	static const char foreign_sibling_mount[] =
		"36 25 259:9 / / rw - ext4 /dev/foreign-root rw\n"
		"37 36 8:2 / /sibling rw - ext4 /dev/sibling rw\n";
	const dev_t root_device = makedev(8U, 4U);
	const dev_t target_parent = makedev(8U, 0U);
	const dev_t changed_parent = makedev(8U, 8U);
	struct swapz_primary_mount_facts facts = {0};
	int result;

	/* Changes after the self read but before the other PID scan are seen. */
	fixture_same_parent_root();
	fixture_peer_mountinfo_before_peer_scan = foreign_selected_mount;
	expect_mount_identity_admission("timed selected mount before peer scan",
					root_device, target_parent, 0, 0,
					"selected target/cross-namespace");
	fixture_expect_timed_change("timed selected mount before peer scan",
				    fixture_peer_mountinfo_before_peer_scan_injected);

	fixture_same_parent_root();
	fixture_peer_mountinfo_before_peer_scan = foreign_parent_mount;
	expect_mount_identity_admission("timed parent mount before peer scan",
					root_device, target_parent, 0, 0,
					"device ancestry/cross-namespace");
	fixture_expect_timed_change("timed parent mount before peer scan",
				    fixture_peer_mountinfo_before_peer_scan_injected);

	fixture_same_parent_root();
	fixture_peer_mountinfo_before_peer_scan = foreign_selected_bind_mount;
	expect_mount_identity_admission("timed misleading-source bind before peer scan",
					root_device, target_parent, 0, 0,
					"selected device number/cross-namespace");
	fixture_expect_timed_change("timed misleading-source bind before peer scan",
				    fixture_peer_mountinfo_before_peer_scan_injected);

	/* The peer can become unreadable after self was already observed clean. */
	fixture_same_parent_root();
	fixture_mount_open_error_before_peer_scan = EACCES;
	expect_mount_identity_admission("timed peer mountinfo becomes inaccessible",
					root_device, target_parent, 0, EACCES,
					"namespace enumeration/access");
	fixture_expect_timed_change("timed peer mountinfo becomes inaccessible",
				    fixture_mount_open_error_before_peer_scan_injected);

	/*
	 * A peer changing mount namespaces between the two stat calls is NOT eligible
	 * for the shared-namespace shortcut. The foreign table must be read.
	 */
	fixture_same_parent_root();
	fixture_share_mount_namespace();
	/* Before the transition, both synthetic views describe the shared namespace. */
	fixture_file("3031/mountinfo",
		     "36 25 8:4 / / rw - ext4 /dev/root-sibling rw\n");
	fixture_peer_mountinfo_after_namespace_change = foreign_selected_mount;
	fixture_peer_namespace_changes_between_stats = 1;
	expect_mount_identity_admission("peer mount namespace changes before confirming skip",
					root_device, target_parent, 0, 0,
					"namespace identity/cross-namespace");
	fixture_expect_timed_change("peer mount namespace changes before confirming skip",
				    fixture_peer_namespace_changed);

	/* An incomplete PID inventory fails closed even after a clean peer. */
	fixture_same_parent_root();
	fixture_peer_mountinfo_before_peer_scan = foreign_sibling_mount;
	fixture_inventory_readdir_error = EIO;
	expect_mount_identity_admission("timed clean peer then incomplete inventory",
					root_device, target_parent, 0, EIO,
					"complete PID enumeration");
	fixture_expect_timed_change("timed clean peer then incomplete inventory",
				    fixture_peer_mountinfo_before_peer_scan_injected);

	/*
	 * Parent ancestry is supplied by the caller, not discovered here.
	 * A stale parent 8:0 sees a clean scan after a new 8:8 parent mount.
	 * The independent caller must re-resolve ancestry; its fresh argument
	 * then detects the mount. Neither result proves a physical write.
	 */
	fixture_same_parent_root();
	fixture_peer_mountinfo_before_peer_scan = foreign_changed_parent_mount;
	expect_mount_identity_admission("timed changed parent with stale argument",
					root_device, target_parent, 1, 0,
					"stale parent argument (not coordinator admission)");
	fixture_expect_timed_change("timed changed parent with stale argument",
				    fixture_peer_mountinfo_before_peer_scan_injected);
	expect_mount_identity_admission("timed changed parent with refreshed argument",
					root_device, changed_parent, 0, 0,
					"revalidated parent device");

	/*
	 * A mount arriving only after production returns from a foreign peer's
	 * completed leader and task scan is another bounded-snapshot control.
	 * Do not turn an observed clean snapshot into a PASS that asserts the
	 * production coordinator may mutate.
	 */
	fixture_same_parent_root();
	fixture_peer_mountinfo_after_peer_scan = foreign_selected_mount;
	errno = 0;
	result = swapz_primary_read_mount_facts(&facts, target_parent);
	{
		int observed_errno = errno;
		unsigned int completed_reads = fixture_peer_mountinfo_completed_reads;

		if (!fixture_peer_mountinfo_after_peer_scan_injected ||
		    completed_reads == 0U) {
			fprintf(stderr,
				"FAIL: boundary=foreign-post-snapshot case=selected "
				"reason=timing-witness result=%d observed_errno=%d target=%d "
				"completed_peer_reads=%u injected=%d "
				"header_write=NOT_INTERCEPTED mapper=NOT_INTERCEPTED "
				"mkswap=NOT_INTERCEPTED swapon=NOT_INTERCEPTED "
				"limitation=reader-only-procfs-snapshot\n",
				result, observed_errno, facts.target_mounted,
				completed_reads,
				fixture_peer_mountinfo_after_peer_scan_injected);
			++fixture_failures;
		}
		if (fixture_mount_fd != -1) {
			fprintf(stderr,
				"FAIL: boundary=foreign-post-snapshot case=selected "
				"reason=mountinfo-fd-leak result=%d observed_errno=%d target=%d "
				"header_write=NOT_INTERCEPTED mapper=NOT_INTERCEPTED "
				"mkswap=NOT_INTERCEPTED swapon=NOT_INTERCEPTED "
				"limitation=reader-only-procfs-snapshot\n",
				result, observed_errno, facts.target_mounted);
			++fixture_failures;
			(void)close(fixture_mount_fd);
			fixture_mount_fd = -1;
		}
		if (result == 0 &&
		    (!facts.root_mount_seen || facts.root_device != root_device)) {
			fprintf(stderr,
				"FAIL: boundary=foreign-post-snapshot case=selected "
				"reason=root-identity result=%d observed_errno=%d target=%d "
				"root_seen=%d root=%u:%u expected_root=%u:%u "
				"header_write=NOT_INTERCEPTED mapper=NOT_INTERCEPTED "
				"mkswap=NOT_INTERCEPTED swapon=NOT_INTERCEPTED "
				"limitation=reader-only-procfs-snapshot\n",
				result, observed_errno, facts.target_mounted,
				facts.root_mount_seen, major(facts.root_device),
				minor(facts.root_device), major(root_device),
				minor(root_device));
			++fixture_failures;
		} else if (result == 0 && !facts.target_mounted) {
			printf("UNPROVEN: boundary=foreign-post-snapshot case=selected "
			       "result=0 errno=%d target=0 prevented=none "
			       "header_write=NOT_INTERCEPTED mapper=NOT_INTERCEPTED "
			       "mkswap=NOT_INTERCEPTED swapon=NOT_INTERCEPTED "
			       "limitation=reader-only-procfs-snapshot-cannot-prove-kernel-exclusion\n",
			       observed_errno);
		}
		if (fixture_peer_mountinfo_after_peer_scan_injected &&
		    completed_reads > 0U) {
			struct swapz_primary_mount_facts fresh_facts = {0};
			int fresh_result;
			int fresh_errno;

			errno = 0;
			fresh_result =
				swapz_primary_read_mount_facts(&fresh_facts, target_parent);
			fresh_errno = errno;
			if (fresh_result != 0 || !fresh_facts.target_mounted) {
				fprintf(stderr,
					"FAIL: boundary=foreign-post-snapshot case=selected "
					"reason=injected-table-not-observable result=%d "
					"observed_errno=%d target=%d "
					"header_write=NOT_INTERCEPTED mapper=NOT_INTERCEPTED "
					"mkswap=NOT_INTERCEPTED swapon=NOT_INTERCEPTED "
					"limitation=reader-only-procfs-snapshot\n",
					fresh_result, fresh_errno,
					fresh_facts.target_mounted);
				++fixture_failures;
			}
			if (fixture_mount_fd != -1) {
				fprintf(stderr,
					"FAIL: boundary=foreign-post-snapshot case=selected "
					"reason=fresh-read-fd-leak result=%d observed_errno=%d "
					"target=%d header_write=NOT_INTERCEPTED "
					"mapper=NOT_INTERCEPTED mkswap=NOT_INTERCEPTED "
					"swapon=NOT_INTERCEPTED "
					"limitation=reader-only-procfs-snapshot\n",
					fresh_result, fresh_errno,
					fresh_facts.target_mounted);
				++fixture_failures;
				(void)close(fixture_mount_fd);
				fixture_mount_fd = -1;
			}
		}
	}
}

static void expect_parent_relationship(
	const char *case_name, int (*relationship_valid)(dev_t, dev_t),
	dev_t first_parent, dev_t second_parent, int should_allow,
	const char *safety_gate)
{
	int result;

	errno = 0;
	result = relationship_valid(first_parent, second_parent);
	if ((result != 0) != should_allow ||
	    (!should_allow && errno != EPERM)) {
		fprintf(stderr,
			"FAIL: %s: gate=%s result=%d errno=%d parents=%u:%u,%u:%u "
			"(expected %s)\n",
			case_name, safety_gate, result, errno,
			major(first_parent), minor(first_parent),
			major(second_parent), minor(second_parent),
			should_allow ? "valid relationship" : "EPERM refusal");
		++fixture_failures;
	}
}

static void test_shared_root_parent_relationship_gates(void)
{
	const dev_t shared_parent = makedev(8U, 0U);

	/* A relationship check is not the independent host scope authorization. */
	expect_parent_relationship("equal target/root parents",
				   swapz_primary_shared_root_parent_relationship_valid,
				   shared_parent, shared_parent, 1,
				   "device ancestry");
	expect_parent_relationship("changed target/root parent",
				   swapz_primary_shared_root_parent_relationship_valid,
				   makedev(8U, 8U), shared_parent, 0,
				   "device ancestry");
	expect_parent_relationship("unresolved target parent",
				   swapz_primary_shared_root_parent_relationship_valid,
				   0, shared_parent, 0, "unresolved identity");
	expect_parent_relationship("unresolved root parent",
				   swapz_primary_shared_root_parent_relationship_valid,
				   shared_parent, 0, 0, "unresolved identity");
	/* Recovery must remain on a different physical parent even in this scope. */
	expect_parent_relationship("shared recovery parent refused",
				   swapz_primary_recovery_parent_separation_valid,
				   shared_parent, shared_parent, 0,
				   "device ancestry/recovery");
	expect_parent_relationship("unresolved recovery target parent",
				   swapz_primary_recovery_parent_separation_valid,
				   0, makedev(259U, 0U), 0,
				   "unresolved identity");
	expect_parent_relationship("unresolved recovery parent",
				   swapz_primary_recovery_parent_separation_valid,
				   shared_parent, 0, 0, "unresolved identity");
	expect_parent_relationship("independent recovery parent accepted",
				   swapz_primary_recovery_parent_separation_valid,
				   shared_parent, makedev(259U, 0U), 1,
				   "device ancestry/recovery");
}

static int fixture_remove_entry(const char *path, const struct stat *info,
				int type, struct FTW *tree)
{
	(void)info;
	(void)type;
	(void)tree;
	return remove(path);
}

static void test_active_swapfile_gate(void)
{
	static const char swapfile_path[] = "/swapfile";
	int active;

	fixture_reset();
	fixture_file("swaps",
		     "Filename Type Size Used Priority\n"
		     "/swapfile file 8192 1 -2\n");
	fixture_regular_swap_path = swapfile_path;

	/* Unrelated host swapfiles remain permitted. */
	fixture_regular_swap_device = makedev(259U, 9U);
	errno = 0;
	if (swapz_primary_original_swap_is_quiescent() < 0) {
		fprintf(stderr,
			"FAIL: unrelated regular swapfile was rejected: errno=%d\n",
			errno);
		++fixture_failures;
	}
	active = swapz_primary_swap_device_active(makedev(8U, 1U));
	if (active != 0) {
		fprintf(stderr,
			"FAIL: unrelated regular swapfile matched selected device: %d\n",
			active);
		++fixture_failures;
	}

	/*
	 * Regular /proc/swaps entries carry no block st_rdev. Production must use
	 * the file's filesystem st_dev so a directly backed active swapfile cannot
	 * bypass the independent selected-storage gate.
	 */
	fixture_regular_swap_device = makedev(8U, 1U);
	errno = 0;
	if (swapz_primary_original_swap_is_quiescent() == 0) {
		fprintf(stderr,
			"FAIL: active swapfile on selected filesystem was admitted\n");
		++fixture_failures;
	}
	active = swapz_primary_swap_device_active(makedev(8U, 1U));
	if (active != 1) {
		fprintf(stderr,
			"FAIL: selected-filesystem swapfile active result=%d errno=%d\n",
			active, errno);
		++fixture_failures;
	}

	/* The same stat identity rule applies when independently checking parent. */
	fixture_regular_swap_device = makedev(8U, 0U);
	active = swapz_primary_swap_device_active(makedev(8U, 0U));
	if (active != 1) {
		fprintf(stderr,
			"FAIL: parent-filesystem swapfile active result=%d errno=%d\n",
			active, errno);
		++fixture_failures;
	}

	/* /proc/swaps type and stat mode must agree before identity is trusted. */
	fixture_file("swaps",
		     "Filename Type Size Used Priority\n"
		     "/swapfile partition 8192 1 -2\n");
	active = swapz_primary_swap_device_active(makedev(8U, 0U));
	if (active >= 0) {
		fprintf(stderr,
			"FAIL: swap partition type accepted a regular file: %d\n",
			active);
		++fixture_failures;
	}
	fixture_file("swaps",
		     "Filename Type Size Used Priority\n"
		     "/swapfile unknown 8192 1 -2\n");
	active = swapz_primary_swap_device_active(makedev(8U, 0U));
	if (active >= 0) {
		fprintf(stderr,
			"FAIL: unknown swap type was accepted: %d\n", active);
		++fixture_failures;
	}
}

static void test_independent_admission_gates(void)
{
	struct swapz_primary_swap_entry entries[2] = {0};
	struct swapz_primary_target wrong_device = swapz_primary_selected_target;
	dev_t devices[2] = {0};
	unsigned char is_block[2] = {0};
	char holder_path[PATH_MAX];
	int length;

	/* Use production geometry/major:minor identity, never the source label. */
	assert(swapz_primary_target_identity_equal(
		&swapz_primary_selected_target, &wrong_device));
	wrong_device.device_minor = 2U;
	assert(!swapz_primary_target_identity_equal(
		&swapz_primary_selected_target, &wrong_device));

	/* An unrelated active swapfile is not a selected block-swap alias. */
	strcpy(entries[0].path, "/unrelated-swapfile");
	strcpy(entries[0].type, "file");
	assert(swapz_primary_swap_inventory_target_is_quiescent(
		entries, devices, is_block, 1U, makedev(8U, 1U), 4096U) == 0);
	strcpy(entries[1].path, "/dev/selected");
	strcpy(entries[1].type, "partition");
	entries[1].size_kib = 4096U;
	entries[1].used_kib = 1U;
	devices[1] = makedev(8U, 1U);
	is_block[1] = 1;
	assert(swapz_primary_swap_inventory_target_is_quiescent(
		entries, devices, is_block, 2U, makedev(8U, 1U), 4096U) < 0);

	assert(swapz_primary_mapper_identity_is_swapz("swapz-selected", "") == 1);
	assert(swapz_primary_mapper_identity_is_swapz("unrelated", "SWAPZ-owned") == 1);
	assert(swapz_primary_mapper_identity_is_swapz("unrelated", "CRYPT-other") == 0);

	length = snprintf(holder_path, sizeof(holder_path), "%s/holders", fixture_proc_root);
	assert(length > 0 && (size_t)length < sizeof(holder_path));
	assert(mkdir(holder_path, 0700) == 0);
	assert(swapz_primary_sysfs_directory_empty(holder_path, 0));
	fixture_file("holders/dm-5", "holder\n");
	assert(!swapz_primary_sysfs_directory_empty(holder_path, 0));
	fixture_unlink("holders/dm-5");
	assert(rmdir(holder_path) == 0);
}


/* A clean-looking foreign mountinfo view can omit selected or parent mounts. */
static void test_root_filtered_foreign_mountinfo(void)
{
	fixture_reset();
	fixture_file("3031/mountinfo",
		     "36 25 259:9 / / rw - ext4 /foreign-root rw\n"
		     "37 36 8:1 / /selected rw - ext4 /dev/selected rw\n");
	expect_mount_admission("complete foreign-root view detects selected", 0, 0);

	/*
	 * The process-root-filtered table is syntactically clean and omits the
	 * selected mount. The pinned namespace inventory retains that hidden row,
	 * so admission must be busy rather than trusting pre/post root strings.
	 */
	fixture_reset();
	fixture_hidden_namespace_kind = FIXTURE_NAMESPACE_FOREIGN_LEADER;
	fixture_hidden_namespace_device = makedev(8U, 1U);
	fixture_file("3031/mountinfo",
		     "36 25 259:9 / / rw - ext4 /filtered-root rw\n");
	expect_mount_admission("namespace inventory catches filtered selected", 0, 0);
	if (fixture_namespace_inventory_scans[
		    FIXTURE_NAMESPACE_FOREIGN_LEADER] == 0U) {
		fprintf(stderr,
			"FAIL: case=foreign-filtered-selected "
			"reason=pinned-namespace-inventory-not-run expected=busy\n");
		++fixture_failures;
	}

	fixture_reset();
	fixture_hidden_namespace_kind = FIXTURE_NAMESPACE_FOREIGN_LEADER;
	fixture_hidden_namespace_device = makedev(8U, 0U);
	fixture_file("3031/mountinfo",
		     "36 25 259:9 / / rw - ext4 /filtered-root rw\n");
	expect_mount_admission("namespace inventory catches filtered parent", 0, 0);

	/* Unsupported direct namespace inventory is ambiguity, never clearance. */
	fixture_reset();
	fixture_namespace_inventory_error_kind = FIXTURE_NAMESPACE_FOREIGN_LEADER;
	fixture_namespace_inventory_error = EOPNOTSUPP;
	expect_mount_admission("unsupported foreign namespace inventory", 0,
			       EOPNOTSUPP);

	fixture_reset();
	fixture_root_statx_error_kind = FIXTURE_NAMESPACE_FOREIGN_LEADER;
	fixture_root_statx_error = EACCES;
	expect_mount_admission("unreadable foreign process root", 0, EACCES);

	/* The already-scanned coordinator namespace safely covers this peer. */
	fixture_reset();
	fixture_share_mount_namespace();
	expect_mount_admission("same-namespace filtered peer shortcut remains safe",
			       1, 0);
}

int main(void)
{
	char proc_template[] = "/tmp/swapz-primary-proc-XXXXXX";
	char path[PATH_MAX];
	const int exit_errors[] = {EINVAL, ENOENT, ESRCH};
	size_t index;

	assert(mkdtemp(proc_template));
	assert(strlen(proc_template) < sizeof(fixture_proc_root));
	strcpy(fixture_proc_root, proc_template);
	assert(snprintf(path, sizeof(path), "%s/self", fixture_proc_root) > 0);
	assert(mkdir(path, 0700) == 0);
	assert(snprintf(path, sizeof(path), "%s/self/ns", fixture_proc_root) > 0);
	assert(mkdir(path, 0700) == 0);
	assert(snprintf(path, sizeof(path), "%s/self/task", fixture_proc_root) > 0);
	assert(mkdir(path, 0700) == 0);
	assert(snprintf(path, sizeof(path), "%s/self/task/65535",
			fixture_proc_root) > 0);
	assert(mkdir(path, 0700) == 0);
	assert(snprintf(path, sizeof(path), "%s/3031", fixture_proc_root) > 0);
	assert(mkdir(path, 0700) == 0);
	assert(snprintf(path, sizeof(path), "%s/3031/ns", fixture_proc_root) > 0);
	assert(mkdir(path, 0700) == 0);
	assert(snprintf(path, sizeof(path), "%s/3031/task", fixture_proc_root) > 0);
	assert(mkdir(path, 0700) == 0);
	assert(snprintf(path, sizeof(path), "%s/3031/task/3031",
			fixture_proc_root) > 0);
	assert(mkdir(path, 0700) == 0);
	strcpy(swapz_primary_selected_target.partuuid, "f13428f6-01");
	swapz_primary_selected_target.device_major = 8U;
	swapz_primary_selected_target.device_minor = 1U;
	swapz_primary_selected_target.device_bytes =
		16ULL * 1024ULL * 1024ULL * 1024ULL;
	fixture_reset();
	expect_mount_admission("only local root mount", 1, 0);
	assert(snprintf(path, sizeof(path), "%s/self/task/65536",
			fixture_proc_root) > 0);
	assert(mkdir(path, 0700) == 0);
	assert(snprintf(path, sizeof(path), "%s/self/task/65536/ns",
			fixture_proc_root) > 0);
	assert(mkdir(path, 0700) == 0);
	fixture_file("self/task/65536/ns/mnt",
		     "coordinator non-leader mount namespace\n");
	/* The leader is unchanged: only this task's selected mount may refuse. */
	fixture_file("self/task/65536/mountinfo",
		     "36 25 259:10 / / rw - ext4 /thread-root rw\n"
		     "37 36 8:2 / /sibling rw - ext4 /dev/sda2 rw\n");
	expect_mount_admission("unrelated sibling in coordinator non-leader thread",
			       1, 0);
	expect_task_mountinfo_open_count(
		"unrelated sibling in coordinator non-leader thread",
		fixture_coordinator_task_mountinfo_opens, 1U);
	fixture_coordinator_task_mountinfo_opens = 0U;
	fixture_file("self/task/65536/mountinfo",
		     "36 25 259:10 / / rw - ext4 /thread-root rw\n"
		     "37 36 8:1 / /selected rw - ext4 /dev/sda1 rw\n");
	expect_mount_admission("selected partition in coordinator non-leader thread",
			       0, 0);
	expect_task_mountinfo_open_count(
		"selected partition in coordinator non-leader thread",
		fixture_coordinator_task_mountinfo_opens, 1U);
	fixture_unlink("self/task/65536/ns/mnt");
	fixture_unlink("self/task/65536/mountinfo");
	assert(snprintf(path, sizeof(path), "%s/self/task/65536/ns",
			fixture_proc_root) > 0);
	assert(rmdir(path) == 0);
	assert(snprintf(path, sizeof(path), "%s/self/task/65536",
			fixture_proc_root) > 0);
	assert(rmdir(path) == 0);
	fixture_reset();
	fixture_file("3031/mountinfo",
		     "36 25 259:9 / / rw - ext4 /dev/other-root rw\n"
		     "37 36 8:2 / /other rw - ext4 /dev/sda2 rw\n");
	expect_mount_admission("unrelated sibling", 1, 0);
	/* An apparent /dev/sda1 source with a different major:minor is not ours. */
	fixture_file("3031/mountinfo",
		     "36 25 259:9 / / rw - ext4 /dev/other-root rw\n"
		     "37 36 8:2 / /selected rw - ext4 /dev/sda1 rw\n");
	expect_mount_admission("wrong-device alias", 1, 0);
	fixture_file("3031/mountinfo",
		     "36 25 259:9 / / rw - ext4 /dev/other-root rw\n"
		     "37 36 8:1 / /selected rw - ext4 /dev/sda1 rw\n");
	expect_mount_admission("selected partition in another namespace", 0, 0);
	/* An unrelated sibling earlier in the same remote table cannot mask it. */
	fixture_file("3031/mountinfo",
		     "36 25 259:9 / / rw - ext4 /dev/other-root rw\n"
		     "37 36 8:2 / /sibling rw - ext4 /dev/sda2 rw\n"
		     "38 36 8:1 / /selected rw - ext4 /dev/sda1 rw\n");
	expect_mount_admission("foreign sibling followed by selected partition", 0, 0);
	fixture_file("3031/mountinfo",
		     "36 25 259:9 / / rw - ext4 /dev/other-root rw\n"
		     "37 36 8:0 / /parent rw - ext4 /dev/sda rw\n");
	expect_mount_admission("selected parent in another namespace", 0, 0);
	fixture_reset();

	/*
	 * Linux exposes non-leader thread /proc/<tid> paths without returning
	 * them from top-level /proc enumeration. A thread can hold a distinct
	 * mount namespace, so a process-leader-only scan must not authorize a
	 * selected target or parent that is mounted only in that thread's view.
	 */
	assert(snprintf(path, sizeof(path), "%s/3031/task/3032", fixture_proc_root) > 0);
	assert(mkdir(path, 0700) == 0);
	assert(snprintf(path, sizeof(path), "%s/3031/task/3032/ns", fixture_proc_root) > 0);
	assert(mkdir(path, 0700) == 0);
	fixture_file("3031/task/3032/ns/mnt", "non-leader thread mount namespace\n");
	fixture_file("3031/task/3032/mountinfo",
		     "36 25 259:10 / / rw - ext4 /dev/thread-root rw\n"
		     "37 36 8:1 / /selected rw - ext4 /dev/sda1 rw\n");
	expect_mount_admission("selected partition in non-leader thread namespace",
			       0, 0);
	expect_task_mountinfo_open_count(
		"selected partition in non-leader thread namespace",
		fixture_foreign_task_mountinfo_opens, 1U);
	fixture_reset();
	fixture_file("3031/task/3032/mountinfo",
		     "36 25 259:10 / / rw - ext4 /dev/thread-root rw\n"
		     "37 36 8:0 / /parent rw - ext4 /dev/sda rw\n");
	expect_mount_admission("selected parent in non-leader thread namespace",
			       0, 0);
	expect_task_mountinfo_open_count(
		"selected parent in non-leader thread namespace",
		fixture_foreign_task_mountinfo_opens, 1U);
	fixture_reset();
	fixture_file("3031/task/3032/mountinfo",
		     "36 25 259:10 / / rw - ext4 /dev/thread-root rw\n"
		     "37 36 8:2 / /sibling rw - ext4 /dev/sda2 rw\n");
	expect_mount_admission("unrelated sibling in non-leader thread namespace",
			       1, 0);
	expect_task_mountinfo_open_count(
		"unrelated sibling in non-leader thread namespace",
		fixture_foreign_task_mountinfo_opens, 1U);
	fixture_reset();
	fixture_share_mount_namespace();
	fixture_file("3031/task/3032/ns/mnt",
		     "non-leader thread mount namespace\n");
	fixture_file("3031/task/3032/mountinfo",
		     "36 25 259:10 / / rw - ext4 /dev/thread-root rw\n"
		     "37 36 8:2 / /sibling rw - ext4 /dev/sda2 rw\n");
	fixture_task_mount_open_error = EACCES;
	expect_mount_admission("unreadable non-leader task mountinfo", 0,
			       EACCES);
	if (!fixture_task_mount_open_error_injected) {
		fprintf(stderr,
			"FAIL: phase=task-mountinfo-access "
			"case=unreadable non-leader task mountinfo "
			"expected=task-specific EACCES refusal actual=injection-not-run "
			"observed_errno=%d header_write=NOT_INTERCEPTED "
			"mapper=NOT_INTERCEPTED mkswap=NOT_INTERCEPTED "
			"swapon=NOT_INTERCEPTED limitation=reader-only-procfs-snapshot "
			"safe_action=retain_inactive_target\n", errno);
		++fixture_failures;
	}
	fixture_reset();
	fixture_share_mount_namespace();
	fixture_file("3031/task/3032/ns/mnt",
		     "non-leader thread mount namespace\n");
	fixture_file("3031/task/3032/mountinfo",
		     "36 25 259:10 / / rw - ext4 /dev/thread-root rw\n"
		     "37 36 8:2 / /sibling rw - ext4 /dev/sda2 rw\n");
	fixture_task_readdir_error = EIO;
	expect_mount_admission("non-leader task enumeration error", 0, EIO);
	expect_task_mountinfo_open_count(
		"non-leader task enumeration error",
		fixture_foreign_task_mountinfo_opens, 1U);
	fixture_reset();
	fixture_file("3031/task/3032/mountinfo", "malformed\n");
	expect_mount_admission("malformed non-leader task mountinfo", 0, EINVAL);
	expect_task_mountinfo_open_count(
		"malformed non-leader task mountinfo",
		fixture_foreign_task_mountinfo_opens, 1U);
	fixture_reset();
	fixture_file("3031/task/3032/mountinfo",
		     "36 25 259:10 / / rw - ext4 /dev/thread-root rw\n"
		     "37 36 8:2 / /sibling rw - ext4 /dev/sda2 rw\n");
	fixture_task_namespace_reuse_on_stat = 1;
	expect_mount_admission("reused non-leader TID changes namespace", 0, EAGAIN);
	expect_task_mountinfo_open_count(
		"reused non-leader TID changes namespace",
		fixture_foreign_task_mountinfo_opens, 1U);
	if (!fixture_task_namespace_reuse_injected) {
		fprintf(stderr,
			"FAIL: phase=task-namespace case=reused TID "
			"expected=EAGAIN refusal actual=injection-not-run "
			"observed_errno=%d header_write=NOT_INTERCEPTED "
			"mapper=NOT_INTERCEPTED mkswap=NOT_INTERCEPTED "
			"swapon=NOT_INTERCEPTED "
			"limitation=reader-only-procfs-snapshot "
			"safe_action=retain_inactive_target\n", errno);
		++fixture_failures;
	}
	if (fixture_task_namespace_reuse_injected)
		fixture_unlink("3031/task/3032/ns/mnt.retired");

	/*
	 * A leader may be absent from /proc/<pid>/ns/mnt while the task directory
	 * still exposes a live non-leader. A vanished leader must never hide that
	 * task's selected partition or selected physical parent.
	 */
	expect_surviving_task_with_missing_leader_namespace(
		"missing leader marker with live selected task",
		"36 25 259:10 / / rw - ext4 /thread-root rw\n"
		"37 36 8:1 / /selected rw - ext4 /dev/selected rw\n",
		FIXTURE_LEADER_NAMESPACE_ABSENT_BEFORE_SCAN);
	expect_surviving_task_with_missing_leader_namespace(
		"missing leader marker with live parent-mounted task",
		"36 25 259:10 / / rw - ext4 /thread-root rw\n"
		"37 36 8:0 / /parent rw - ext4 /dev/parent rw\n",
		FIXTURE_LEADER_NAMESPACE_ABSENT_BEFORE_SCAN);
	expect_surviving_task_with_missing_leader_namespace(
		"leader marker lost during confirmation with live selected task",
		"36 25 259:10 / / rw - ext4 /thread-root rw\n"
		"37 36 8:1 / /selected rw - ext4 /dev/selected rw\n",
		FIXTURE_LEADER_NAMESPACE_LOST_DURING_CONFIRMATION);
	expect_surviving_task_with_missing_leader_namespace(
		"leader marker lost after mountinfo open error with live parent task",
		"36 25 259:10 / / rw - ext4 /thread-root rw\n"
		"37 36 8:0 / /parent rw - ext4 /dev/parent rw\n",
		FIXTURE_LEADER_NAMESPACE_LOST_ON_MOUNTINFO_OPEN);

	/* Exercise both finite task-count and aggregate mountinfo-byte ceilings. */
	fixture_reset();
	expect_nonleader_bound_refusal(
		"non-leader visible task ceiling",
		SWAPZ_PRIMARY_VISIBLE_TASKS_MAX, 0U, 0U);
	fixture_reset();
	expect_nonleader_bound_refusal(
		"aggregate non-leader mountinfo byte ceiling",
		1U, SWAPZ_PRIMARY_MOUNTINFO_TOTAL_BYTES, 1U);


	/*
	 * A non-leader can expose a filtered mountinfo while its pinned namespace
	 * still contains selected storage. The namespace inventory must catch it.
	 */
	fixture_reset();
	fixture_file("3031/task/3032/ns/mnt", "live worker mount namespace\n");
	fixture_file("3031/task/3032/mountinfo",
		     "36 25 259:10 / / rw - ext4 /filtered-worker-root rw\n");
	fixture_hidden_namespace_kind = FIXTURE_NAMESPACE_FOREIGN_TASK;
	fixture_hidden_namespace_device = makedev(8U, 1U);
	expect_mount_admission("filtered foreign non-leader namespace", 0, 0);
	if (fixture_namespace_inventory_scans[
		    FIXTURE_NAMESPACE_FOREIGN_TASK] == 0U) {
		fprintf(stderr,
			"FAIL: case=filtered-foreign-nonleader "
			"reason=pinned-namespace-inventory-not-run expected=busy\n");
		++fixture_failures;
	}

	/* A task that is gone before namespace inspection is safe to skip. */
	fixture_reset();
	fixture_unlink("3031/task/3032/mountinfo");
	fixture_unlink("3031/task/3032/ns/mnt");
	expect_mount_admission("vanished non-leader TID", 1, 0);
	expect_task_mountinfo_open_count(
		"vanished non-leader TID",
		fixture_foreign_task_mountinfo_opens, 0U);
	assert(snprintf(path, sizeof(path), "%s/3031/task/3032/ns", fixture_proc_root) > 0);
	assert(rmdir(path) == 0);
	assert(snprintf(path, sizeof(path), "%s/3031/task/3032", fixture_proc_root) > 0);
	assert(rmdir(path) == 0);
	fixture_reset();
	fixture_file("self/mountinfo",
		     "36 25 259:0 / / rw - ext4 /dev/root rw\n"
		     "37 36 8:1 / /selected rw - ext4 /dev/sda1 rw\n");
	expect_mount_admission("selected partition mounted locally", 0, 0);
	fixture_reset();
	fixture_file("self/mountinfo",
		     "36 25 259:0 / / rw - ext4 /dev/root rw\n"
		     "37 36 8:0 / /parent rw - ext4 /dev/sda rw\n");
	expect_mount_admission("selected parent mounted locally", 0, 0);

	fixture_reset();
	fixture_file("self/mountinfo", "malformed\n");
	expect_mount_admission("malformed local mount table", 0, EINVAL);
	fixture_reset();
	fixture_unlink("self/mountinfo");
	expect_mount_admission("missing local mount table", 0, ENOENT);
	fixture_reset();
	fixture_file("3031/mountinfo", "malformed\n");
	expect_mount_admission("malformed remote mount table", 0, EINVAL);
	fixture_reset();
	fixture_file("3031/mountinfo",
		     "36 25 259:9 / / rw future:field - ext4 /dev/other-root rw\n");
	expect_mount_admission("unknown optional field remains extensible", 1, 0);
	fixture_reset();
	fixture_file("3031/mountinfo",
		     "36 25 259:9 / / bogus - ext4 /dev/other-root rw\n");
	expect_mount_admission("invalid mount options", 0, EINVAL);
	fixture_reset();
	fixture_file("3031/mountinfo",
		     "36 25 259:9 / / rw shared:1 shared:2 - ext4 /dev/other-root rw\n");
	expect_mount_admission("duplicate known optional field", 0, EINVAL);
	fixture_reset();
	fixture_file("3031/mountinfo",
		     "36 25 0259:9 / / rw - ext4 /dev/other-root rw\n");
	expect_mount_admission("noncanonical mounted device", 0, EINVAL);
	fixture_reset();
	fixture_file("3031/mountinfo",
		     "36 25 259:9 / /bad\\141 rw - ext4 /dev/other-root rw\n");
	expect_mount_admission("invalid mountpoint escape", 0, EINVAL);
	fixture_reset();
	fixture_file("3031/mountinfo",
		     "36 25 259:9 / / rw - ext4 /dev/other-root rw\n"
		     "37 36 8:2 / /sibling rw - ext4 /dev/sda2 rw\n"
		     "37 36 8:3 / /other rw - ext4 /dev/sda3 rw\n");
	expect_mount_admission("duplicate mount identifier", 0, EINVAL);
	fixture_reset();
	fixture_file("3031/mountinfo",
		     "36 25 259:9 / / rw - ext4 /dev/other-root rw\n"
		     "37 36 8:2 / /sibling rw - ext4 /dev/sda2 rw");
	expect_mount_admission("unterminated complete remote mount row", 0, EINVAL);
	fixture_reset();
	{
		static const unsigned char embedded_nul_mountinfo[] =
			"36 25 259:9 / / rw - ext4 /dev/other-root rw\n\0"
			"37 36 8:1 / /selected rw - ext4 /dev/sda1 rw\n";

		fixture_bytes("3031/mountinfo", embedded_nul_mountinfo,
			      sizeof(embedded_nul_mountinfo) - 1U);
	}
	expect_mount_admission("embedded NUL cannot hide selected mount", 0, EINVAL);
	fixture_reset();
	fixture_file("3031/mountinfo", "");
	expect_mount_admission("empty remote mount table", 0, EINVAL);
	fixture_reset();
	fixture_share_mount_namespace();
	fixture_file("3031/mountinfo", "");
	expect_mount_admission("same-namespace chroot with empty mount table", 1, 0);
	fixture_reset();
	fixture_share_mount_namespace();
	strcpy(fixture_self_root, "/coordinator-chroot");
	fixture_file("3031/mountinfo", "");
	expect_mount_admission("chrooted coordinator keeps empty peer ambiguous",
			       0, EAGAIN);
	fixture_reset();
	fixture_share_mount_namespace();
	fixture_file("self/mountinfo",
		     "36 25 259:0 / / rw - ext4 /dev/root rw\n"
		     "37 36 8:1 / /selected rw - ext4 /dev/selected rw\n");
	fixture_file("3031/mountinfo", "");
	expect_mount_admission("full-root inventory catches same-namespace mount",
			       0, 0);
	/* A partial final mount row must fail parsing, not hide selected 8:1. */
	fixture_reset();
	fixture_file("3031/mountinfo",
		     "36 25 259:9 / / rw - ext4 /dev/other-root rw\n"
		     "37 36 8:1 / /selected rw - ext4 /dev/selected");
	expect_mount_admission("truncated remote mount row", 0, EINVAL);
	fixture_reset();
	fixture_file("self/mountinfo",
		     "36 25 259:0 / / rw - ext4 /dev/root rw\n"
		     "37 36 8:1 / /selected rw - ext4 /dev/selected");
	expect_mount_admission("truncated local mount row", 0, EINVAL);
	fixture_reset();
	fixture_oversized_file("3031/mountinfo");
	expect_mount_admission("oversized remote mount table", 0, EOVERFLOW);
	if (errno != EOVERFLOW) {
		fprintf(stderr, "FAIL: remote overflow errno=%d\n", errno);
		++fixture_failures;
	}
	fixture_reset();
	fixture_oversized_file("self/mountinfo");
	expect_mount_admission("oversized local mount table", 0, EOVERFLOW);
	if (errno != EOVERFLOW) {
		fprintf(stderr, "FAIL: local overflow errno=%d\n", errno);
		++fixture_failures;
	}
	fixture_reset();
	fixture_self_mount_open_error = EACCES;
	expect_mount_admission("unreadable local mount table", 0, EACCES);
	if (errno != EACCES) {
		fprintf(stderr, "FAIL: unreadable local errno=%d\n", errno);
		++fixture_failures;
	}
	fixture_reset();
	fixture_unlink("self/mountinfo");
	assert(snprintf(path, sizeof(path), "%s/self/mountinfo", fixture_proc_root) > 0);
	assert(symlink("../3031/mountinfo", path) == 0);
	expect_mount_admission("no-follow local mountinfo symlink", 0, ELOOP);
	if (errno != ELOOP) {
		fprintf(stderr, "FAIL: symlink mountinfo errno=%d\n", errno);
		++fixture_failures;
	}
	fixture_unlink("self/mountinfo");
	fixture_reset();
	fixture_mount_read_error = EIO;
	expect_mount_admission("opened remote table read error", 0, EIO);
	fixture_reset();
	fixture_mount_close_error = EIO;
	expect_mount_admission("opened remote table close error", 0, EIO);
	fixture_reset();
	fixture_inventory_error = EACCES;
	expect_mount_admission("permission-denied PID inventory", 0, EACCES);
	fixture_reset();
	fixture_inventory_readdir_error = EIO;
	expect_mount_admission("PID inventory fails after enumerating foreign PID", 0, EIO);
	fixture_reset();
	fixture_mount_vanish_on_read = 1;
	expect_mount_admission("opened foreign table vanishes during read", 0, ESRCH);
	fixture_reset();
	fixture_mount_open_error = EACCES;
	expect_mount_admission("permission-denied remote table", 0, EACCES);
	fixture_reset();
	fixture_unlink("3031/mountinfo");
	expect_mount_admission("missing table with live namespace", 0, ENOENT);

	for (index = 0; index < sizeof(exit_errors) / sizeof(exit_errors[0]); ++index) {
		fixture_reset();
		fixture_mount_open_error = exit_errors[index];
		expect_mount_admission("exit errno with live namespace", 0, exit_errors[index]);
		fixture_unlink("3031/ns/mnt");
		expect_mount_admission("exit errno with absent namespace", 1, 0);
	}
	fixture_reset();
	fixture_mount_open_error = EINVAL;
	fixture_namespace_stat_error = EACCES;
	expect_mount_admission("uninspectable namespace is not process exit", 0, EACCES);
	fixture_reset();
	fixture_unlink("3031/mountinfo");
	fixture_unlink("3031/ns/mnt");
	expect_mount_admission("missing table and vanished namespace", 1, 0);
	test_shared_root_parent_mount_gates();
	test_root_filtered_foreign_mountinfo();
	probe_shared_root_parent_same_namespace_snapshot_gap();
	test_controlled_mount_snapshot_timings();
	test_shared_root_parent_relationship_gates();
	test_active_swapfile_gate();
	test_independent_admission_gates();
	assert(nftw(fixture_proc_root, fixture_remove_entry, 16,
		    FTW_DEPTH | FTW_PHYS) == 0);
	if (fixture_failures) {
		fprintf(stderr, "FAIL: primary mount namespace %u cases\n",
			fixture_failures);
		return 1;
	}
	puts("PASS: primary manager production mount namespace admission");
	return 0;
}
