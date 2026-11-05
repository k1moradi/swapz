// SPDX-License-Identifier: GPL-2.0-only
#define _GNU_SOURCE
#include <stdio.h>
#include <sys/types.h>
#include <unistd.h>

#include <dirent.h>
#include <fcntl.h>
#include <ftw.h>
#include <stdarg.h>
#include <stdlib.h>
#include <sys/ioctl.h>
#include <sys/stat.h>

/* Interpose only synthetic sysfs/proc and a fake block descriptor. */
static int admission_open(const char *path, int flags, ...);
static int admission_fcntl(int fd, int command, ...);
static int admission_fprintf(FILE *stream, const char *format, ...);
static inline void admission_perror(const char *description);
static int admission_close(int fd);
static int admission_stat(const char *path, struct stat *info);
static int admission_lstat(const char *path, struct stat *info);
static int admission_fstat(int fd, struct stat *info);
static int admission_ioctl(int fd, unsigned long request, ...);
static ssize_t admission_pread(int fd, void *buffer, size_t length, off_t offset);
static int admission_fsync(int fd);
static DIR *admission_opendir(const char *path);
static char *admission_realpath(const char *path, char *resolved);

/* Inject bounded I/O faults into the real formatter helpers. */
static unsigned int test_pwrite_calls;
static int test_pwrite_short;
static const char *test_fopen_denied_path;
static ssize_t test_format_pwrite(int fd, const void *buffer, size_t length,
				  off_t offset);
static FILE *test_format_fopen(const char *path, const char *mode);

#define open(...) admission_open(__VA_ARGS__)
#define fcntl(...) admission_fcntl(__VA_ARGS__)
#define fprintf(...) admission_fprintf(__VA_ARGS__)
#define perror(...) admission_perror(__VA_ARGS__)
#define close(...) admission_close(__VA_ARGS__)
#define stat(...) admission_stat(__VA_ARGS__)
#define lstat(...) admission_lstat(__VA_ARGS__)
#define fstat(...) admission_fstat(__VA_ARGS__)
#define ioctl(...) admission_ioctl(__VA_ARGS__)
#define pread(...) admission_pread(__VA_ARGS__)
#define fsync(...) admission_fsync(__VA_ARGS__)
#define opendir(...) admission_opendir(__VA_ARGS__)
#define realpath(...) admission_realpath(__VA_ARGS__)
#define pwrite test_format_pwrite
#define fopen test_format_fopen
#define main swapzctl_program_main
#include "../../../../src/userspace/swapzctl.c"
#undef main
#undef perror
#undef fprintf
#undef fcntl
#undef fopen
#undef pwrite
#undef realpath
#undef opendir
#undef fsync
#undef pread
#undef ioctl
#undef fstat
#undef lstat
#undef stat
#undef close
#undef open

#include <assert.h>

static int test_format_mountinfo_stream_clear(FILE *stream, dev_t device,
					      dev_t parent_device)
{
	int empty_table = 0;

	if (format_mountinfo_stream_clear_details(
		    stream, device, parent_device, NULL, &empty_table) < 0)
		return -1;
	if (empty_table) {
		errno = EPROTO;
		return -1;
	}
	return 0;
}

#define format_mountinfo_line_device(line, device) \
	format_mountinfo_line_device_with_root((line), (device), NULL)
#define format_mountinfo_stream_clear(stream, device, parent_device) \
	test_format_mountinfo_stream_clear((stream), (device), (parent_device))

/* Make libc diagnostic errno clobber deterministic in the formatter. */
static int test_diagnostic_errno_clobber;

static int admission_fprintf(FILE *stream, const char *format, ...)
{
	va_list arguments;
	int written;

	va_start(arguments, format);
	written = vfprintf(stream, format, arguments);
	va_end(arguments);
	if (stream == stderr && test_diagnostic_errno_clobber)
		errno = test_diagnostic_errno_clobber;
	return written;
}

static inline void admission_perror(const char *description)
{
	perror(description);
	if (test_diagnostic_errno_clobber)
		errno = test_diagnostic_errno_clobber;
}

/*
 * Rootless CLI integration: default formatter callbacks consume actual
 * source-extracted sysfs/proc parsers. Fake device FD is never an OS FD.
 * Snapshot tests do not establish kernel-level BLK_EXCL / swapon exclusion.
 */
enum admission_change {
	ADMISSION_UNCHANGED,
	ADMISSION_BAD_PARTUUID,
	ADMISSION_PARENT_CHANGED,
	ADMISSION_SWAPFILE_ACTIVE,
	ADMISSION_PARENT_MOUNTED,
	ADMISSION_FOREIGN_DENIED,
	ADMISSION_LIVE_PID_TABLE_MISSING,
	ADMISSION_GEOMETRY_CHANGED,
	ADMISSION_ALIAS_CHANGED,
	ADMISSION_PATH_SYMLINK,
	ADMISSION_PATH_INODE_CHANGED,
	ADMISSION_PATH_REGULAR_CHANGED,
	ADMISSION_OPENED_RO_QUERY_FAILED,
	ADMISSION_OPENED_READ_ONLY,
	ADMISSION_SWAP_INVENTORY_MALFORMED,
	ADMISSION_EXITED_PID_CONTROL,
	ADMISSION_PARTITION_DISAPPEARS,
};
#define ADMISSION_DIAGNOSTIC_BYTES 1024U
#define ADMISSION_DEVICE_FD 987654
#define ADMISSION_DEVICE "/dev/swapz-synthetic-card"
#define ADMISSION_ALIAS "/dev/disk/by-partuuid/f13428f6-01"
#define ADMISSION_PARENT "/sys/devices/usb1/disk"
#define ADMISSION_SWAP_HEADER \
	"Filename\t\t\t\tType\t\tSize\t\tUsed\t\tPriority\n"

static struct {
	char root[PATH_MAX];
	unsigned char block_zero[SWAPZ_SUPERBLOCK_BYTES];
	unsigned long long geometry_bytes;
	dev_t alias_device;
	ino_t path_inode;
	enum admission_change change;
	unsigned int opens, reads, writes, syncs, closes;
	unsigned int partition_path_stats;
	const char *observed_identity;
	unsigned int observed_identity_calls;
	int enabled, path_is_symlink, path_is_regular;
	int open_error, observed_open_flags;
	int descriptor_mode, descriptor_error, close_error;
	unsigned int descriptor_queries;
	/* Borrowed late table, injected only after the first fake header read. */
	const char *late_swap_inventory;
	unsigned int swap_inventory_checks;
	int late_swap_unreadable;
} admission_fixture;

static int admission_fcntl(int fd, int command, ...)
{
	if (admission_fixture.enabled && fd == ADMISSION_DEVICE_FD) {
		assert(command == F_GETFL);
		admission_fixture.descriptor_queries++;
		if (admission_fixture.descriptor_error) {
			errno = admission_fixture.descriptor_error;
			return -1;
		}
		return admission_fixture.descriptor_mode;
	}
	return fcntl(fd, command);
}

static void admission_observe_identity(const char *identity)
{
	if (!identity || !admission_fixture.reads)
		return;
	admission_fixture.observed_identity = identity;
	++admission_fixture.observed_identity_calls;
}

static const char *admission_route(const char *path, char mapped[PATH_MAX])
{
	int size;

	if (!admission_fixture.enabled ||
	    (strcmp(path, "/proc") && strcmp(path, "/sys") &&
	     strncmp(path, "/proc/", 6U) &&
	     strncmp(path, "/sys/", 5U)))
		return path;
	size = snprintf(mapped, PATH_MAX, "%s%s", admission_fixture.root, path);
	if (size < 0 || size >= PATH_MAX) {
		errno = ENAMETOOLONG;
		return NULL;
	}
	return mapped;
}

static void admission_write_text(const char *virtual_path, const char *value)
{
	char mapped[PATH_MAX];
	FILE *file;

	assert(admission_route(virtual_path, mapped) == mapped);
	file = fopen(mapped, "w");
	assert(file != NULL);
	assert(fputs(value, file) >= 0);
	assert(fclose(file) == 0);
}

static void admission_unlink(const char *virtual_path)
{
	char mapped[PATH_MAX];

	assert(admission_route(virtual_path, mapped) == mapped);
	assert(unlink(mapped) == 0);
}

static void admission_after_first_read(void)
{
	switch (admission_fixture.change) {
	case ADMISSION_BAD_PARTUUID:
		admission_write_text("/sys/dev/block/8:1/uevent",
				     "PARTUUID=deadbeef-01\n");
		break;
	case ADMISSION_PARENT_CHANGED:
		admission_write_text(ADMISSION_PARENT "/dev", "8:16\n");
		break;
	case ADMISSION_SWAPFILE_ACTIVE:
		admission_write_text("/proc/swaps", ADMISSION_SWAP_HEADER
				     "/unresolvable/swapfile file 4 1 -2\n");
		break;
	case ADMISSION_SWAP_INVENTORY_MALFORMED:
		admission_write_text("/proc/swaps", "Filename\tType\n");
		break;
	case ADMISSION_PARENT_MOUNTED:
		admission_write_text("/proc/3031/mountinfo",
				     "37 25 8:0 / /card rw - ext4 /dev/parent rw\n");
		break;
	case ADMISSION_FOREIGN_DENIED:
		test_fopen_denied_path = "/proc/3031/mountinfo";
		break;
	case ADMISSION_LIVE_PID_TABLE_MISSING:
		admission_unlink("/proc/3031/mountinfo");
		break;
	case ADMISSION_GEOMETRY_CHANGED:
		admission_fixture.geometry_bytes -= SWAPZ_SUPERBLOCK_BYTES;
		break;
	case ADMISSION_ALIAS_CHANGED:
		admission_fixture.alias_device = makedev(8U, 2U);
		break;
	case ADMISSION_PATH_SYMLINK:
		admission_fixture.path_is_symlink = 1;
		break;
	case ADMISSION_PATH_INODE_CHANGED:
		++admission_fixture.path_inode;
		break;
	case ADMISSION_PATH_REGULAR_CHANGED:
		++admission_fixture.path_inode;
		admission_fixture.path_is_regular = 1;
		break;
	case ADMISSION_EXITED_PID_CONTROL:
		admission_unlink("/proc/3031/mountinfo");
		admission_unlink("/proc/3031/ns/mnt");
		break;
	case ADMISSION_UNCHANGED:
	case ADMISSION_OPENED_RO_QUERY_FAILED:
	case ADMISSION_OPENED_READ_ONLY:
	case ADMISSION_PARTITION_DISAPPEARS:
		break;
	}
	if (admission_fixture.late_swap_inventory)
		admission_write_text("/proc/swaps",
				     admission_fixture.late_swap_inventory);
	if (admission_fixture.late_swap_unreadable)
		test_fopen_denied_path = "/proc/swaps";
}

static struct stat admission_block_stat(dev_t device, ino_t inode)
{
	const struct stat info = {
		.st_mode = S_IFBLK | 0600, .st_uid = 0,
		.st_dev = makedev(0U, 7U), .st_rdev = device, .st_ino = inode,
	};
	return info;
}

static int admission_stat(const char *path, struct stat *info)
{
	char mapped[PATH_MAX];
	const char *actual;

	if (admission_fixture.enabled && !strcmp(path, ADMISSION_ALIAS)) {
		if (admission_fixture.change == ADMISSION_ALIAS_CHANGED)
			admission_observe_identity("by-partuuid-alias");
		*info = admission_block_stat(admission_fixture.alias_device, 17U);
		return 0;
	}
	if (admission_fixture.enabled &&
	    admission_fixture.change == ADMISSION_PARTITION_DISAPPEARS &&
	    !strcmp(path, ADMISSION_PARENT "/part") &&
	    ++admission_fixture.partition_path_stats > 1U) {
		errno = ENOENT;
		return -1;
	}
	if (admission_fixture.enabled && !strncmp(path, "/dev/", 5U)) {
		errno = ENOENT;
		return -1;
	}
	actual = admission_route(path, mapped);
	return actual ? stat(actual, info) : -1;
}

static int admission_lstat(const char *path, struct stat *info)
{
	char mapped[PATH_MAX];
	const char *actual;

	if (admission_fixture.enabled && !strcmp(path, ADMISSION_DEVICE)) {
		if (admission_fixture.change == ADMISSION_PATH_SYMLINK)
			admission_observe_identity("path-symlink-substitution");
		else if (admission_fixture.change == ADMISSION_PATH_INODE_CHANGED)
			admission_observe_identity("same-dev_t-new-inode");
		*info = admission_block_stat(makedev(8U, 1U),
					    admission_fixture.path_inode);
		if (admission_fixture.path_is_symlink)
			info->st_mode = S_IFLNK | 0777;
		else if (admission_fixture.path_is_regular) {
			admission_observe_identity("path-terminal-regular-replacement");
			info->st_mode = S_IFREG | 0600;
			info->st_rdev = 0;
		}
		return 0;
	}
	if (admission_fixture.enabled && !strncmp(path, "/dev/", 5U)) {
		errno = ENOENT;
		return -1;
	}
	actual = admission_route(path, mapped);
	return actual ? lstat(actual, info) : -1;
}

static int admission_fstat(int fd, struct stat *info)
{
	if (admission_fixture.enabled && fd == ADMISSION_DEVICE_FD) {
		*info = admission_block_stat(makedev(8U, 1U), 17U);
		return 0;
	}
	return fstat(fd, info);
}

static int admission_open(const char *path, int flags, ...)
{
	char mapped[PATH_MAX];
	const char *actual;
	mode_t mode = 0;

	if (admission_fixture.enabled && admission_fixture.reads) {
		if (admission_fixture.change == ADMISSION_BAD_PARTUUID &&
		    !strcmp(path, "/sys/dev/block/8:1/uevent"))
			admission_observe_identity("sysfs-PARTUUID");
		else if (admission_fixture.change == ADMISSION_PARENT_CHANGED &&
			 !strcmp(path, ADMISSION_PARENT "/dev"))
			admission_observe_identity("parent-dev_t");
	}

	if (flags & O_CREAT) {
		va_list arguments;
		va_start(arguments, flags);
		mode = (mode_t)va_arg(arguments, int);
		va_end(arguments);
	}
	if (admission_fixture.enabled && !strcmp(path, ADMISSION_DEVICE)) {
		admission_fixture.observed_open_flags = flags;
		++admission_fixture.opens;
		/* Check requested flags, not actual kernel exclusivity. */
		if (flags != (O_RDWR | O_EXCL | O_CLOEXEC | O_NOFOLLOW)) {
			errno = EPERM;
			return -1;
		}
		if (admission_fixture.open_error) {
			errno = admission_fixture.open_error;
			return -1;
		}
		return ADMISSION_DEVICE_FD;
	}
	if (admission_fixture.enabled && !strncmp(path, "/dev/", 5U)) {
		errno = EPERM;
		return -1;
	}
	actual = admission_route(path, mapped);
	if (!actual)
		return -1;
	return flags & O_CREAT ? open(actual, flags, mode) : open(actual, flags);
}

static int admission_close(int fd)
{
	if (admission_fixture.enabled && fd == ADMISSION_DEVICE_FD) {
		++admission_fixture.closes;
		if (admission_fixture.close_error) {
			errno = admission_fixture.close_error;
			return -1;
		}
		return 0;
	}
	return close(fd);
}

static int admission_ioctl(int fd, unsigned long request, ...)
{
	va_list arguments;
	void *argument;

	va_start(arguments, request);
	argument = va_arg(arguments, void *);
	va_end(arguments);
	if (admission_fixture.enabled && fd == ADMISSION_DEVICE_FD) {
		if (request == BLKGETSIZE64) {
			if (admission_fixture.change == ADMISSION_GEOMETRY_CHANGED)
				admission_observe_identity("BLKGETSIZE64");
			*(unsigned long long *)argument =
				admission_fixture.geometry_bytes;
			return 0;
		}
		if (request == BLKROGET) {
			if (admission_fixture.reads &&
			    admission_fixture.change ==
				    ADMISSION_OPENED_RO_QUERY_FAILED) {
				admission_observe_identity("opened-BLKROGET-ENODEV");
				errno = ENODEV;
				return -1;
			}
			if (admission_fixture.reads &&
			    admission_fixture.change == ADMISSION_OPENED_READ_ONLY) {
				admission_observe_identity("opened-BLKROGET-read-only");
				*(int *)argument = 1;
			} else {
				*(int *)argument = 0;
			}
			return 0;
		}
		errno = ENOTTY;
		return -1;
	}
	return ioctl(fd, request, argument);
}

static ssize_t admission_pread(int fd, void *buffer, size_t length, off_t offset)
{
	if (admission_fixture.enabled && fd == ADMISSION_DEVICE_FD) {
		if (offset != 0 || length != sizeof(admission_fixture.block_zero)) {
			errno = EINVAL;
			return -1;
		}
		memcpy(buffer, admission_fixture.block_zero, length);
		if (++admission_fixture.reads == 1U)
			admission_after_first_read();
		return (ssize_t)length;
	}
	return pread(fd, buffer, length, offset);
}

static int admission_fsync(int fd)
{
	if (admission_fixture.enabled && fd == ADMISSION_DEVICE_FD) {
		++admission_fixture.syncs;
		return 0;
	}
	return fsync(fd);
}

static DIR *admission_opendir(const char *path)
{
	char mapped[PATH_MAX];
	const char *actual = admission_route(path, mapped);
	return actual ? opendir(actual) : NULL;
}

static char *admission_realpath(const char *path, char *resolved)
{
	char mapped[PATH_MAX], local[PATH_MAX];
	const char *actual = admission_route(path, mapped);
	size_t root_length;

	if (!actual || !resolved)
		return NULL;
	if (!admission_fixture.enabled || strncmp(path, "/sys/", 5U))
		return realpath(actual, resolved);
	if (!realpath(actual, local))
		return NULL;
	root_length = strlen(admission_fixture.root);
	if (strncmp(local, admission_fixture.root, root_length) ||
	    strncmp(local + root_length, "/sys/", 5U)) {
		errno = ENODEV;
		return NULL;
	}
	strcpy(resolved, local + root_length); /* The shortened path fits. */
	return resolved;
}

static int admission_cleanup(const char *path, const struct stat *info,
			     int type, struct FTW *walk)
{
	(void)info;
	(void)type;
	(void)walk;
	return remove(path);
}

static void admission_make_directory(const char *virtual_path)
{
	char mapped[PATH_MAX];
	assert(admission_route(virtual_path, mapped) == mapped);
	assert(mkdir(mapped, 0700) == 0);
}

static void admission_start(enum admission_change change)
{
	static const char *const dirs[] = {
		"/sys", "/sys/dev", "/sys/dev/block", "/sys/devices",
		"/sys/devices/usb1", ADMISSION_PARENT,
		ADMISSION_PARENT "/part", ADMISSION_PARENT "/part/holders",
		ADMISSION_PARENT "/part/slaves", ADMISSION_PARENT "/holders",
		ADMISSION_PARENT "/slaves", ADMISSION_PARENT "/queue",
		"/proc", "/proc/self", "/proc/self/ns", "/proc/3031",
		"/proc/3031/ns",
	};
	char path[PATH_MAX];

	memset(&admission_fixture, 0, sizeof(admission_fixture));
	assert(snprintf(admission_fixture.root, sizeof(admission_fixture.root),
			"/tmp/swapzctl-admission-XXXXXX") > 0);
	assert(mkdtemp(admission_fixture.root) != NULL);
	admission_fixture.enabled = 1;
	admission_fixture.change = change;
	admission_fixture.geometry_bytes = 124787884032ULL;
	admission_fixture.alias_device = makedev(8U, 1U);
	admission_fixture.path_inode = 17U;
	admission_fixture.descriptor_mode = O_RDWR;
	for (size_t index = 0; index < sizeof(dirs) / sizeof(dirs[0]); ++index)
		admission_make_directory(dirs[index]);

	assert(admission_route("/sys/dev/block/8:1", path) == path);
	assert(symlink("../../devices/usb1/disk/part", path) == 0);
	assert(admission_route(ADMISSION_PARENT "/device", path) == path);
	assert(symlink("..", path) == 0);
	assert(admission_route("/proc/self/root", path) == path);
	assert(symlink("/", path) == 0);
	admission_write_text(ADMISSION_PARENT "/part/dev", "8:1\n");
	admission_write_text(ADMISSION_PARENT "/part/partition", "1\n");
	admission_write_text("/sys/dev/block/8:1/uevent",
			     "MAJOR=8\nMINOR=1\nPARTUUID=f13428f6-01\n");
	admission_write_text(ADMISSION_PARENT "/dev", "8:0\n");
	admission_write_text(ADMISSION_PARENT "/removable", "1\n");
	admission_write_text("/sys/devices/usb1/model", "Multi-Card\n");
	admission_write_text("/proc/self/ns/mnt", "self namespace\n");
	admission_write_text(
		"/proc/self/mountinfo",
		"1 42 8:9 / / rw - ext4 /dev/root rw\n"
		"36 25 0:20 / /proc rw - proc proc rw\n");
	admission_write_text("/proc/3031/mountinfo",
			     "37 25 8:2 / /sibling rw - ext4 /dev/sibling rw\n");
	admission_write_text("/proc/3031/ns/mnt", "namespace\n");
	admission_write_text("/proc/swaps", ADMISSION_SWAP_HEADER);
}

static void admission_stop(void)
{
	test_fopen_denied_path = NULL;
	admission_fixture.enabled = 0;
	assert(nftw(admission_fixture.root, admission_cleanup, 8,
		    FTW_DEPTH | FTW_PHYS) == 0);
}

static int admission_format_cli(void)
{
	char *argv[] = {
		"swapzctl", "format", ADMISSION_DEVICE,
		"--expect-major-minor", "8:1",
		"--expect-bytes", "124787884032",
		"--expect-partuuid", "f13428f6-01",
		"--expect-parent-major-minor", "8:0",
		"--expect-parent-model", "Multi-Card",
		"--expect-parent-transport", "usb",
	};

	return swapzctl_program_main((int)(sizeof(argv) / sizeof(argv[0])), argv);
}

static int admission_capture_cli(
	char report[ADMISSION_DIAGNOSTIC_BYTES], int *observed_errno)
{
	FILE *diagnostics;
	int saved_stderr, status;
	size_t length;

	assert(report != NULL && observed_errno != NULL);
	diagnostics = tmpfile();
	assert(diagnostics != NULL);
	assert(fflush(stderr) == 0);
	saved_stderr = dup(STDERR_FILENO);
	assert(saved_stderr >= 0);
	assert(dup2(fileno(diagnostics), STDERR_FILENO) >= 0);
	errno = 0;
	status = admission_format_cli();
	*observed_errno = errno;
	assert(fflush(stderr) == 0);
	assert(dup2(saved_stderr, STDERR_FILENO) >= 0);
	assert(close(saved_stderr) == 0);
	assert(fseek(diagnostics, 0L, SEEK_SET) == 0);
	length = fread(report, 1U, ADMISSION_DIAGNOSTIC_BYTES - 1U,
		       diagnostics);
	assert(!ferror(diagnostics));
	report[length] = '\0';
	assert(fclose(diagnostics) == 0);
	return status;
}

/*
 * An exclusive-open permission denial must not acquire the fake descriptor.
 * O_EXCL matching here does not establish loaded-kernel BLK_EXCL.
 */
static void test_real_cli_exclusive_open_permission_refuses_without_io(void)
{
	const unsigned char unchanged[SWAPZ_SUPERBLOCK_BYTES] = {0};
	char report[ADMISSION_DIAGNOSTIC_BYTES] = {0};
	char errno_field[64];
	int errno_length;
	int status, observed_errno;

	errno_length = snprintf(errno_field, sizeof(errno_field), "errno=%d (",
				EACCES);
	assert(errno_length > 0 && (size_t)errno_length < sizeof(errno_field));
	admission_start(ADMISSION_UNCHANGED);
	admission_fixture.open_error = EACCES;
	test_diagnostic_errno_clobber = ECHILD;
	status = admission_capture_cli(report, &observed_errno);
	test_diagnostic_errno_clobber = 0;
	if (status != 1 || observed_errno != EACCES ||
	    !strstr(report, "swapzctl format: exclusive open:") ||
	    !strstr(report, "stage=exclusive open") ||
	    !strstr(report, "expected=O_RDWR | O_EXCL | O_CLOEXEC | O_NOFOLLOW") ||
	    !strstr(report, "action=") ||
	    !strstr(report, errno_field) ||
	    !strstr(report, strerror(EACCES)) ||
	    strstr(report, ADMISSION_DEVICE) ||
	    admission_fixture.observed_open_flags !=
		    (O_RDWR | O_EXCL | O_CLOEXEC | O_NOFOLLOW) ||
	    admission_fixture.opens != 1U ||
	    admission_fixture.reads != 0U ||
	    admission_fixture.writes != 0U ||
	    admission_fixture.syncs != 0U ||
	    admission_fixture.closes != 0U ||
	    memcmp(admission_fixture.block_zero, unchanged,
		   sizeof(unchanged))) {
		fprintf(stderr, "FAIL: phase=exclusive-open "
			"prerequisite=permission-denied errno=%d "
			"expected_errno=%d status=%d opens=%u reads=%u "
			"writes=%u syncs=%u\n",
			observed_errno, EACCES, status, admission_fixture.opens,
			admission_fixture.reads, admission_fixture.writes,
			admission_fixture.syncs);
		abort();
	}
	admission_stop();
}

static void test_real_cli_snapshots_refuse_before_first_header_write(void)
{
	static const struct {
		enum admission_change change;
		const char *observed_identity;
		int expected_errno;
		const char *expected_stage;
		const char *expected_condition;
	} cases[] = {
		{ ADMISSION_BAD_PARTUUID, "sysfs-PARTUUID", ESTALE,
		  "identity", "sysfs PARTUUID matches the expected opened block identity" },
		{ ADMISSION_PARENT_CHANGED, "parent-dev_t", ESTALE,
		  "topology", "expected removable USB parent" },
		{ ADMISSION_SWAPFILE_ACTIVE, "active-swapfile-unauthenticated",
		  EOPNOTSUPP, "inventory", "absent from mount namespaces and /proc/swaps" },
		{ ADMISSION_PARENT_MOUNTED, "foreign-parent-mount", EBUSY,
		  "inventory", "absent from mount namespaces and /proc/swaps" },
		{ ADMISSION_FOREIGN_DENIED, "foreign-mount-namespace-EACCES",
		  EACCES, "inventory", "absent from mount namespaces and /proc/swaps" },
		{ ADMISSION_LIVE_PID_TABLE_MISSING, "live-pid-mountinfo-missing",
		  ENOENT, "inventory", "absent from mount namespaces and /proc/swaps" },
		{ ADMISSION_GEOMETRY_CHANGED, "BLKGETSIZE64", ESTALE,
		  "identity", "opened descriptor inode and geometry match" },
		{ ADMISSION_ALIAS_CHANGED, "by-partuuid-alias", ESTALE,
		  "identity", "opened descriptor inode and geometry match" },
		{ ADMISSION_PATH_SYMLINK, "path-symlink-substitution", ESTALE,
		  "identity", "opened descriptor inode and geometry match" },
		{ ADMISSION_PATH_INODE_CHANGED, "same-dev_t-new-inode", ESTALE,
		  "identity", "opened descriptor inode and geometry match" },
		{ ADMISSION_PATH_REGULAR_CHANGED,
		  "path-terminal-regular-replacement", ESTALE,
		  "identity", "opened descriptor inode and geometry match" },
		{ ADMISSION_OPENED_RO_QUERY_FAILED, "opened-BLKROGET-ENODEV",
		  ENODEV, "descriptor mode", "BLKROGET == 0" },
		{ ADMISSION_OPENED_READ_ONLY, "opened-BLKROGET-read-only",
		  EROFS, "descriptor mode", "BLKROGET == 0" },
		{ ADMISSION_SWAP_INVENTORY_MALFORMED,
		  "malformed-late-swap-inventory", EPROTO,
		  "inventory", "absent from mount namespaces and /proc/swaps" },
	};
	const unsigned char unchanged[SWAPZ_SUPERBLOCK_BYTES] = {0};

	for (size_t index = 0; index < sizeof(cases) / sizeof(cases[0]);
	     ++index) {
		char report[ADMISSION_DIAGNOSTIC_BYTES] = {0};
		int status, observed_errno;

		admission_start(cases[index].change);
		test_diagnostic_errno_clobber = ECHILD;
		status = admission_capture_cli(report, &observed_errno);
		test_diagnostic_errno_clobber = 0;

		{
			char stage_field[64];
			char errno_field[64];
			int field_length;

			field_length = snprintf(stage_field, sizeof(stage_field),
						"stage=%s",
						cases[index].expected_stage);
			assert(field_length > 0 &&
			       (size_t)field_length < sizeof(stage_field));
			field_length = snprintf(errno_field, sizeof(errno_field),
						"errno=%d (",
						cases[index].expected_errno);
			assert(field_length > 0 &&
			       (size_t)field_length < sizeof(errno_field));
			if (status != 2 ||
			    observed_errno != cases[index].expected_errno ||
			    !strstr(report, "REFUSED: target identity changed before "
				    "header write") ||
			    !strstr(report, stage_field) ||
			    !strstr(report, cases[index].expected_condition) ||
			    !strstr(report, errno_field) ||
			    !strstr(report, "action=") ||
			    !strstr(report, strerror(cases[index].expected_errno)) ||
			    !admission_fixture.observed_identity ||
			    strcmp(admission_fixture.observed_identity,
				   cases[index].observed_identity) ||
			    admission_fixture.observed_identity_calls != 1U ||
			    strstr(report, ADMISSION_DEVICE) ||
			    admission_fixture.opens != 1U ||
			    admission_fixture.reads != 1U ||
			    admission_fixture.writes != 0U ||
			    admission_fixture.syncs != 0U ||
			    admission_fixture.closes != 1U ||
			    memcmp(admission_fixture.block_zero, unchanged,
				   sizeof(unchanged))) {
				fprintf(stderr, "FAIL: phase=final-prewrite "
					"reason=snapshot-refusal expected_stage=%s "
					"expected_identity=%s observed_identity=%s "
					"identity_reads=%u errno=%d expected_errno=%d "
					"status=%d opens=%u reads=%u writes=%u\n",
					cases[index].expected_stage,
					cases[index].observed_identity,
					admission_fixture.observed_identity ?
						admission_fixture.observed_identity : "none",
					admission_fixture.observed_identity_calls,
					observed_errno, cases[index].expected_errno,
					status, admission_fixture.opens,
					admission_fixture.reads,
					admission_fixture.writes);
				abort();
			}
		}
		admission_stop();
	}

	/*
	 * Negative control: an exited PID whose mount namespace is gone is
	 * skippable; absence of mountinfo with a LIVE namespace above is not.
	 * The sole successful write here modifies in-memory fake block zero.
	 */
	admission_start(ADMISSION_EXITED_PID_CONTROL);
	assert(admission_format_cli() == 0);
	assert(admission_fixture.opens == 1U);
	assert(admission_fixture.writes == 1U);
	assert(admission_fixture.syncs == 1U);
	assert(swapz_sb_valid(admission_fixture.block_zero,
			      admission_fixture.geometry_bytes));
	admission_stop();
	puts("PASS: rootless CLI snapshot admission; kernel exclusivity NOT PROVEN");
}


/*
 * Parser-only failures are not proof that the real CLI refuses before pwrite.
 * Exercise its default pre-open and last prewrite inventory gates with fake
 * procfs and an in-memory block zero; no actual block descriptor is opened.
 */
static void test_real_cli_active_swap_inventory_never_writes(void)
{
	static const struct {
		const char *scenario;
		const char *inventory;
		const char *observed_entries;
		const char *entry_class;
		int expected_errno;
		int late;
		int inaccessible;
	} cases[] = {
		{ "active-regular", ADMISSION_SWAP_HEADER
		  "/unresolvable/swapfile file 4 1 -2\n",
		  "1", "regular", EOPNOTSUPP, 0, 0 },
		{ "active-partition", ADMISSION_SWAP_HEADER
		  "/dev/other partition 4 1 -2\n",
		  "1", "partition", EOPNOTSUPP, 0, 0 },
		{ "duplicated", ADMISSION_SWAP_HEADER
		  "/unresolvable/swapfile file 4 1 -2\n"
		  "/unresolvable/swapfile file 4 1 -3\n",
		  "2", "duplicate", EOPNOTSUPP, 0, 0 },
		{ "malformed-header", "Filename Type Size Used Priority\n",
		  "0", "malformed-header", EPROTO, 0, 0 },
		{ "malformed-after-active", ADMISSION_SWAP_HEADER
		  "/unresolvable/swapfile file 4 1 -2\n"
		  "/unresolvable/swapfile file 4 1\n",
		  "2", "malformed-row", EPROTO, 0, 0 },
		{ "truncated", ADMISSION_SWAP_HEADER
		  "/unresolvable/swapfile file 4 1 -2",
		  "1", "truncated-row", EPROTO, 0, 0 },
		{ "empty", "", "0", "empty", EPROTO, 0, 0 },
		{ "inaccessible", NULL, "unknown", "unreadable",
		  EACCES, 0, 1 },
		{ "late-active", ADMISSION_SWAP_HEADER
		  "/unresolvable/swapfile file 4 1 -2\n",
		  "1", "regular", EOPNOTSUPP, 1, 0 },
		{ "late-duplicated", ADMISSION_SWAP_HEADER
		  "/unresolvable/swapfile file 4 1 -2\n"
		  "/unresolvable/swapfile file 4 1 -3\n",
		  "2", "duplicate", EOPNOTSUPP, 1, 0 },
		{ "late-truncated", ADMISSION_SWAP_HEADER
		  "/unresolvable/swapfile file 4 1 -2",
		  "1", "truncated-row", EPROTO, 1, 0 },
		{ "late-inaccessible", NULL, "unknown", "unreadable",
		  EACCES, 1, 1 },
	};

	for (size_t index = 0; index < sizeof(cases) / sizeof(cases[0]);
	     ++index) {
		unsigned char original_block[SWAPZ_SUPERBLOCK_BYTES];
		char report[ADMISSION_DIAGNOSTIC_BYTES] = {0};
		char errno_field[64];
		const char *expected_summary = cases[index].late ?
			"REFUSED: target identity changed before header write" :
			"REFUSED: pre-open admission is not proven";
		unsigned int previous_pwrite_calls;
		unsigned int expected_inventory_checks = cases[index].late ? 3U : 1U;
		unsigned int expected_open_calls = cases[index].late ? 1U : 0U;
		int unchanged, observed_errno, status;
		int length;

		admission_start(ADMISSION_UNCHANGED);
		memcpy(original_block, admission_fixture.block_zero,
		       sizeof(original_block));
		previous_pwrite_calls = test_pwrite_calls;
		if (cases[index].late) {
			admission_fixture.late_swap_inventory = cases[index].inventory;
			admission_fixture.late_swap_unreadable =
				cases[index].inaccessible;
		} else if (cases[index].inaccessible) {
			test_fopen_denied_path = "/proc/swaps";
		} else {
			admission_write_text("/proc/swaps", cases[index].inventory);
		}

		length = snprintf(errno_field, sizeof(errno_field), "errno=%d (",
				  cases[index].expected_errno);
		assert(length > 0 && (size_t)length < sizeof(errno_field));
		test_diagnostic_errno_clobber = ECHILD;
		status = admission_capture_cli(report, &observed_errno);
		test_diagnostic_errno_clobber = 0;
		unchanged = !memcmp(admission_fixture.block_zero, original_block,
				    sizeof(original_block));

		if (status != 2 || observed_errno != cases[index].expected_errno ||
		    !strstr(report, expected_summary) ||
		    !strstr(report, "stage=inventory") ||
		    !strstr(report, "expected=") ||
		    !strstr(report, errno_field) ||
		    !strstr(report, "action=") ||
		    !strstr(report, strerror(cases[index].expected_errno)) ||
		    strstr(report, ADMISSION_DEVICE) ||
		    admission_fixture.swap_inventory_checks !=
			    expected_inventory_checks ||
		    admission_fixture.opens != expected_open_calls ||
		    admission_fixture.reads != expected_open_calls ||
		    admission_fixture.closes != expected_open_calls ||
		    admission_fixture.writes != 0U ||
		    admission_fixture.syncs != 0U ||
		    test_pwrite_calls != previous_pwrite_calls || !unchanged) {
			fprintf(stderr, "FAIL: phase=active_swap_inventory "
				"scenario=%s gate=%s observed_entries=%s entry_class=%s "
				"original_errno=%d expected_errno=%d status=%d "
				"operation=header_pwrite expected=refused writes=%u "
				"pwrite_delta=%u block_zero_untouched=%d "
				"inventory_checks=%u opens=%u reads=%u "
				"syncs=%u closes=%u\n",
				cases[index].scenario, cases[index].late ? "prewrite" : "preopen",
				cases[index].observed_entries,
				cases[index].entry_class, observed_errno,
				cases[index].expected_errno, status,
				admission_fixture.writes,
				test_pwrite_calls - previous_pwrite_calls, unchanged,
				admission_fixture.swap_inventory_checks,
				admission_fixture.opens, admission_fixture.reads,
				admission_fixture.syncs, admission_fixture.closes);
			abort();
		}
		admission_stop();
	}
	puts("PASS: rootless active-swap inventory refusals before header pwrite");
}

static void test_missing_partition_slaves_directory_is_empty(void)
{
	char report[ADMISSION_DIAGNOSTIC_BYTES] = {0};
	char path[PATH_MAX];
	int observed_errno;

	/*
	 * Real physical partition sysfs nodes may not expose "slaves". The
	 * synthetic topology keeps the parent edges and all other identity checks.
	 */
	admission_start(ADMISSION_UNCHANGED);
	assert(admission_route(ADMISSION_PARENT "/part/slaves", path) == path);
	assert(rmdir(path) == 0);
	assert(admission_capture_cli(report, &observed_errno) == 0);
	assert(admission_fixture.opens == 1U);
	assert(admission_fixture.reads == 2U);
	assert(admission_fixture.writes == 1U);
	assert(admission_fixture.syncs == 1U);
	assert(admission_fixture.closes == 1U);
	assert(swapz_sb_valid(admission_fixture.block_zero,
			      admission_fixture.geometry_bytes));
	admission_stop();
}

static void test_missing_partition_slaves_does_not_hide_removal(void)
{
	const unsigned char unchanged[SWAPZ_SUPERBLOCK_BYTES] = {0};
	char report[ADMISSION_DIAGNOSTIC_BYTES] = {0};
	char path[PATH_MAX];
	int observed_errno;

	admission_start(ADMISSION_PARTITION_DISAPPEARS);
	assert(admission_route(ADMISSION_PARENT "/part/slaves", path) == path);
	assert(rmdir(path) == 0);
	assert(admission_capture_cli(report, &observed_errno) == 2);
	assert(observed_errno == ENOENT);
	assert(strstr(report, "stage=topology"));
	assert(strstr(report, "errno=2 ("));
	assert(admission_fixture.partition_path_stats == 2U);
	assert(admission_fixture.opens == 0U);
	assert(admission_fixture.reads == 0U);
	assert(admission_fixture.writes == 0U);
	assert(admission_fixture.syncs == 0U);
	assert(admission_fixture.closes == 0U);
	assert(memcmp(admission_fixture.block_zero, unchanged,
		      sizeof(unchanged)) == 0);
	admission_stop();
}

/* The fake descriptor exercises the real final mode check, not BLK_EXCL. */
static void test_real_cli_descriptor_access_modes_refuse_without_write(void)
{
	static const struct {
		int descriptor_mode;
		int descriptor_error;
		int expected_errno;
		const char *failed_stage;
	} cases[] = {
		{ O_RDWR, ENODEV, ENODEV, "descriptor mode query failed" },
		{ O_RDONLY, 0, EBADF, "descriptor mode is not O_RDWR" },
		{ O_WRONLY, 0, EBADF, "descriptor mode is not O_RDWR" },
	};
	const unsigned char unchanged[SWAPZ_SUPERBLOCK_BYTES] = {0};

	for (size_t index = 0; index < sizeof(cases) / sizeof(cases[0]);
	     ++index) {
		char report[ADMISSION_DIAGNOSTIC_BYTES] = {0};
		char errno_field[64];
		int errno_length;
		int status, observed_errno;

		errno_length = snprintf(errno_field, sizeof(errno_field),
					"errno=%d (", cases[index].expected_errno);
		assert(errno_length > 0 &&
		       (size_t)errno_length < sizeof(errno_field));
		admission_start(ADMISSION_UNCHANGED);
		admission_fixture.descriptor_mode = cases[index].descriptor_mode;
		admission_fixture.descriptor_error = cases[index].descriptor_error;
		admission_fixture.close_error = EOVERFLOW;
		test_diagnostic_errno_clobber = ECHILD;
		status = admission_capture_cli(report, &observed_errno);
		test_diagnostic_errno_clobber = 0;
		if (status != 2 || observed_errno != cases[index].expected_errno ||
		    !strstr(report, cases[index].failed_stage) ||
		    !strstr(report, "stage=descriptor mode") ||
		    !strstr(report, "expected=fcntl(F_GETFL)") ||
		    !strstr(report, errno_field) ||
		    !strstr(report, "action=") ||
		    !strstr(report, "CLEANUP FAILED: close") ||
		    !strstr(report, "stage=cleanup") ||
		    strstr(report, ADMISSION_DEVICE) ||
		    admission_fixture.opens != 1U ||
		    admission_fixture.reads != 1U ||
		    admission_fixture.descriptor_queries != 1U ||
		    admission_fixture.writes != 0U ||
		    admission_fixture.syncs != 0U ||
		    admission_fixture.closes != 1U ||
		    memcmp(admission_fixture.block_zero, unchanged,
			   sizeof(unchanged))) {
			fprintf(stderr, "FAIL: stage=descriptor-mode case=%zu "
				"errno=%d expected=%d writes=%u syncs=%u\n",
				index, observed_errno, cases[index].expected_errno,
				admission_fixture.writes, admission_fixture.syncs);
			abort();
		}
		admission_stop();
	}
}

static const char *test_configured_partuuid = "f13428f6-01";
static int test_config_error;

int swapz_primary_target_config_read(
	char partuuid[SWAPZ_PRIMARY_PARTUUID_LENGTH + 1U])
{
	if (test_config_error || !test_configured_partuuid) {
		errno = test_config_error ? test_config_error : ENOENT;
		return -1;
	}
	if (strlen(test_configured_partuuid) > SWAPZ_PRIMARY_PARTUUID_LENGTH) {
		errno = EINVAL;
		return -1;
	}
	strcpy(partuuid, test_configured_partuuid);
	return 0;
}

static ssize_t test_format_pwrite(int fd, const void *buffer, size_t length,
				  off_t offset)
{
	if (admission_fixture.enabled && fd == ADMISSION_DEVICE_FD) {
		++test_pwrite_calls;
		++admission_fixture.writes;
		if (offset != 0 || length != sizeof(admission_fixture.block_zero)) {
			errno = EINVAL;
			return -1;
		}
		memcpy(admission_fixture.block_zero, buffer, length);
		return (ssize_t)length;
	}
	++test_pwrite_calls;
	if (test_pwrite_short)
		return pwrite(fd, buffer, length / 2U, offset);
	return pwrite(fd, buffer, length, offset);
}

static FILE *test_format_fopen(const char *path, const char *mode)
{
	char mapped[PATH_MAX];
	const char *actual;

	if (admission_fixture.enabled && !strcmp(path, "/proc/swaps"))
		++admission_fixture.swap_inventory_checks;
	if (admission_fixture.enabled && admission_fixture.reads) {
		if (admission_fixture.change == ADMISSION_SWAPFILE_ACTIVE &&
		    !strcmp(path, "/proc/swaps"))
			admission_observe_identity("active-swapfile-unauthenticated");
		else if (admission_fixture.change ==
			 ADMISSION_SWAP_INVENTORY_MALFORMED &&
			 !strcmp(path, "/proc/swaps"))
			admission_observe_identity("malformed-late-swap-inventory");
		else if (admission_fixture.change == ADMISSION_PARENT_MOUNTED &&
			 !strcmp(path, "/proc/3031/mountinfo"))
			admission_observe_identity("foreign-parent-mount");
		else if (admission_fixture.change == ADMISSION_FOREIGN_DENIED &&
			 !strcmp(path, "/proc/3031/mountinfo"))
			admission_observe_identity("foreign-mount-namespace-EACCES");
		else if (admission_fixture.change == ADMISSION_LIVE_PID_TABLE_MISSING &&
			 !strcmp(path, "/proc/3031/mountinfo"))
			admission_observe_identity("live-pid-mountinfo-missing");
	}

	if (test_fopen_denied_path && !strcmp(path, test_fopen_denied_path)) {
		errno = EACCES;
		return NULL;
	}
	actual = admission_route(path, mapped);
	return actual ? fopen(actual, mode) : NULL;
}

int swapz_primary_command(int argc, char **argv)
{
	(void)argc;
	(void)argv;
	return 99;
}

struct mock_format_context {
	unsigned char media[SWAPZ_SUPERBLOCK_BYTES];
	int preopen_error;
	int open_error;
	int descriptor_error;
	int descriptor_mode;
	int descriptor_mode_overridden;
	int read_error;
	int random_error;
	int write_error;
	int sync_error;
	int close_error;
	int verify_errors[8];
	size_t verify_error_count;
	size_t verify_error_index;
	int authorization_errors[8];
	size_t authorization_error_count;
	size_t authorization_error_index;
	unsigned int authorization_calls;
	unsigned int preopen_calls;
	unsigned int open_calls;
	unsigned int descriptor_query_calls;
	unsigned int verify_calls;
	unsigned int read_calls;
	unsigned int random_calls;
	unsigned int write_calls;
	unsigned int sync_calls;
	unsigned int close_calls;
	/* Borrowed fixture paths and inventory bytes; tests retain ownership. */
	const char *synthetic_proc_root;
	const char *synthetic_swap_inventory;
	const char *late_swap_inventory;
	const char *replacement_path;
	const char *retired_path;
	int inventory_errno;
	const char *inventory_check;
	unsigned int replacement_calls;
};

static int mock_inventory_verify(struct mock_format_context *context,
				 int final_gate);

static struct format_expectation authorized_expectation(void)
{
	struct format_expectation expected;

	assert(parse_format_expectation("8:1", "8:0", "124787884032",
					"f13428f6-01", &expected) == 0);
	assert(format_parent_expectation("Multi-Card", "usb", &expected) == 0);
	return expected;
}

static int mock_authorized_target_verify(
	void *opaque, const struct format_expectation *expected)
{
	struct mock_format_context *context = opaque;
	int error = 0;

	assert(expected != NULL);
	context->authorization_calls++;
	if (context->authorization_error_index <
	    context->authorization_error_count)
		error = context->authorization_errors[
			context->authorization_error_index++];
	if (error) {
		errno = error;
		return -1;
	}
	return 0;
}

static int mock_preopen_verify(
	void *opaque, const char *path,
	const struct format_expectation *expected,
	struct format_admission_problem *problem)
{
	struct mock_format_context *context = opaque;

	assert(path != NULL);
	assert(expected != NULL);
	context->preopen_calls++;
	format_admission_problem_set(
		problem, FORMAT_ADMISSION_IDENTITY,
		"synthetic pre-open identity matches the expected target");
	if (context->preopen_error) {
		errno = context->preopen_error;
		return -1;
	}
	format_admission_problem_set(
		problem, FORMAT_ADMISSION_INVENTORY,
		"synthetic mount/swap inventory remains clear");
	return mock_inventory_verify(context, 0);
}

static int mock_open_device(void *opaque, const char *path)
{
	struct mock_format_context *context = opaque;

	assert(path != NULL);
	context->open_calls++;
	if (context->open_error) {
		errno = context->open_error;
		return -1;
	}
	return 17;
}

static int mock_descriptor_flags(void *opaque, int fd)
{
	struct mock_format_context *context = opaque;

	assert(fd == 17);
	context->descriptor_query_calls++;
	if (context->descriptor_error) {
		errno = context->descriptor_error;
		return -1;
	}
	return context->descriptor_mode_overridden ?
		context->descriptor_mode : O_RDWR;
}

static int mock_verify_opened(
	void *opaque, int fd, const char *path,
	const struct format_expectation *expected,
	struct format_admission_problem *problem)
{
	struct mock_format_context *context = opaque;
	int error = 0;

	assert(fd == 17);
	assert(path != NULL);
	assert(expected != NULL);
	context->verify_calls++;
	format_admission_problem_set(
		problem, FORMAT_ADMISSION_IDENTITY,
		"synthetic opened identity matches the expected target");
	if (context->verify_error_index < context->verify_error_count)
		error = context->verify_errors[context->verify_error_index++];
	if (error) {
		errno = error;
		return -1;
	}
	format_admission_problem_set(
		problem, FORMAT_ADMISSION_INVENTORY,
		"synthetic mount/swap inventory remains clear");
	return mock_inventory_verify(context, context->verify_calls >= 2U);
}

static int mock_read_header(void *opaque, int fd,
			    unsigned char block[SWAPZ_SUPERBLOCK_BYTES])
{
	struct mock_format_context *context = opaque;

	assert(fd == 17);
	context->read_calls++;
	if (context->read_error) {
		errno = context->read_error;
		return -1;
	}
	memcpy(block, context->media, sizeof(context->media));
	/* Replace the original path after inventory, before the final gate. */
	if (context->replacement_path) {
		int replacement_fd;

		assert(context->retired_path);
		assert(rename(context->replacement_path,
			      context->retired_path) == 0);
		replacement_fd = open(context->replacement_path,
				      O_CREAT | O_EXCL | O_WRONLY | O_CLOEXEC, 0600);
		assert(replacement_fd >= 0);
		assert(close(replacement_fd) == 0);
		context->replacement_path = NULL;
		context->replacement_calls++;
	}
	return 0;
}

static int mock_random_bytes(void *opaque, unsigned char *bytes, size_t length)
{
	struct mock_format_context *context = opaque;

	context->random_calls++;
	if (context->random_error) {
		errno = context->random_error;
		return -1;
	}
	memset(bytes, 0x5a, length);
	return 0;
}

static int mock_write_header(
	void *opaque, int fd,
	const unsigned char block[SWAPZ_SUPERBLOCK_BYTES])
{
	struct mock_format_context *context = opaque;

	assert(fd == 17);
	context->write_calls++;
	if (context->write_error) {
		/*
		 * Model a transport failure after a possible torn publication:
		 * callers must not infer "no bytes written" from an error return.
		 */
		memcpy(context->media, block, sizeof(context->media) / 2U);
		errno = context->write_error;
		return -1;
	}
	memcpy(context->media, block, sizeof(context->media));
	return 0;
}

static int mock_sync_device(void *opaque, int fd)
{
	struct mock_format_context *context = opaque;

	assert(fd == 17);
	context->sync_calls++;
	if (context->sync_error) {
		errno = context->sync_error;
		return -1;
	}
	return 0;
}

static int mock_close_device(void *opaque, int fd)
{
	struct mock_format_context *context = opaque;

	assert(fd == 17);
	context->close_calls++;
	if (context->close_error) {
		errno = context->close_error;
		return -1;
	}
	return 0;
}

static struct format_runtime_ops mock_ops(struct mock_format_context *context)
{
	const struct format_runtime_ops ops = {
		.context = context,
		.authorized_target_verify = mock_authorized_target_verify,
		.preopen_verify = mock_preopen_verify,
		.open_device = mock_open_device,
		.get_descriptor_flags = mock_descriptor_flags,
		.verify_opened = mock_verify_opened,
		.read_header = mock_read_header,
		.random_bytes = mock_random_bytes,
		.write_header = mock_write_header,
		.sync_device = mock_sync_device,
		.close_device = mock_close_device,
	};

	return ops;
}

static void make_valid_header(
	unsigned char header[SWAPZ_SUPERBLOCK_BYTES],
	unsigned long long device_bytes)
{
	memset(header, 0, SWAPZ_SUPERBLOCK_BYTES);
	memcpy(header + SWAPZ_SUPERBLOCK_MAGIC_OFFSET, swapz_superblock_magic,
	       SWAPZ_SUPERBLOCK_MAGIC_BYTES);
	swapz_sb_put_u32(header + SWAPZ_SUPERBLOCK_VERSION_OFFSET,
			 SWAPZ_SUPERBLOCK_VERSION);
	swapz_sb_put_u32(header + SWAPZ_SUPERBLOCK_HEADER_BYTES_OFFSET,
			 SWAPZ_SUPERBLOCK_BYTES);
	swapz_sb_put_u64(header + SWAPZ_SUPERBLOCK_DEVICE_BYTES_OFFSET,
			 device_bytes);
	memset(header + SWAPZ_SUPERBLOCK_UUID_OFFSET, 0x33,
	       SWAPZ_SUPERBLOCK_UUID_BYTES);
}

static void test_numeric_bound_parser(void)
{
	const char *end = NULL;
	unsigned long long value = 0;

	assert(SWAPZ_FORMAT_PROC_MAX_PID_TABLES >= 4U * 1024U * 1024U);
	assert(parse_unsigned_decimal("1", 1ULL, &end, &value) == 0);
	assert(*end == '\0' && value == 1ULL);
	assert(parse_unsigned_decimal("2", 1ULL, &end, &value) < 0);
	assert(parse_unsigned_decimal("01", 10ULL, &end, &value) < 0);
	assert(parse_unsigned_decimal("00", 10ULL, &end, &value) < 0);
	assert(parse_unsigned_decimal("9", 0ULL, &end, &value) < 0);
	assert(parse_unsigned_decimal(NULL, 1ULL, &end, &value) < 0);
	assert(parse_unsigned_decimal("1", 1ULL, NULL, &value) < 0);
	assert(parse_unsigned_decimal("1", 1ULL, &end, NULL) < 0);
	assert(format_parse_text_u64("1\n", 1ULL, &value) == 0);
	assert(value == 1ULL);
	assert(format_parse_text_u64("01\n", 10ULL, &value) < 0);
	assert(format_parse_text_u64("2\n", 1ULL, &value) < 0);
}

static void test_format_expectation_parser(void)
{
	struct format_expectation expected;
	char too_long[SWAPZ_PRIMARY_PARTUUID_LENGTH + 2U];

	assert(parse_format_expectation("8:1", "8:0", "124787884032",
					"F13428F6-01", &expected) == 0);
	assert(expected.device_major == 8U);
	assert(expected.device_minor == 1U);
	assert(expected.parent_major == 8U);
	assert(expected.parent_minor == 0U);
	assert(expected.device_bytes == 124787884032ULL);
	assert(!strcmp(expected.partuuid, "f13428f6-01"));
	assert(format_parent_expectation("Multi-Card", "usb", &expected) == 0);
	assert(!strcmp(expected.parent_model, "Multi-Card"));
	assert(format_parent_expectation("", "usb", &expected) < 0);
	assert(format_parent_expectation(" Multi-Card", "usb", &expected) < 0);
	assert(format_parent_expectation("Multi-Card", "sata", &expected) < 0);
	assert(parse_format_expectation("259:17", "259:16", "8589934592",
					"ABCDEF12-34", &expected) == 0);

	memset(too_long, 'a', sizeof(too_long));
	too_long[sizeof(too_long) - 1U] = '\0';
	assert(parse_format_expectation("8:1", "8:0", "124787884032",
					"--------", &expected) < 0);
	assert(parse_format_expectation("8:1", "8:0", "124787884032",
					"-f13428f6", &expected) < 0);
	assert(parse_format_expectation("8:1", "8:0", "124787884032",
					"f13428f6-", &expected) < 0);
	assert(parse_format_expectation("8:1", "8:0", "124787884032",
					"f13428f6--01", &expected) < 0);
	assert(parse_format_expectation("8:1", "8:0", "124787884032",
					"f13428g6-01", &expected) < 0);
	assert(parse_format_expectation("8:1", "8:0", "124787884032",
					"abc-def", &expected) < 0);
	assert(parse_format_expectation("8:1", "8:0", "124787884032",
					too_long, &expected) < 0);

	assert(parse_format_expectation("-8:1", "8:0", "124787884032",
					"f13428f6-01", &expected) < 0);
	assert(parse_format_expectation("08:1", "8:0", "124787884032",
					"f13428f6-01", &expected) < 0);
	assert(parse_format_expectation("8:01", "8:0", "124787884032",
					"f13428f6-01", &expected) < 0);
	assert(parse_format_expectation("8:1", "8:0", "0124787884032",
					"f13428f6-01", &expected) < 0);
	assert(parse_format_expectation("0:1", "8:0", "124787884032",
					"f13428f6-01", &expected) < 0);
	assert(parse_format_expectation("8:1", "0:0", "124787884032",
					"f13428f6-01", &expected) < 0);
	assert(parse_format_expectation("8:1 ", "8:0", "124787884032",
					"f13428f6-01", &expected) < 0);
	assert(parse_format_expectation("8:1", "8:1", "124787884032",
					"f13428f6-01", &expected) < 0);
	assert(parse_format_expectation("8:1", "8:0", "124787884033",
					"f13428f6-01", &expected) < 0);
	assert(parse_format_expectation("8:1", "8:0", "1",
					"f13428f6-01", &expected) < 0);
	assert(parse_format_expectation("8:1", "8:0",
					"18446744073709551616",
					"f13428f6-01", &expected) < 0);
	assert(parse_format_expectation("4294967296:1", "8:0",
					"124787884032", "f13428f6-01",
					&expected) < 0);
}

static void test_identity_table_rejects_substitution(void)
{
	struct format_expectation expected = authorized_expectation();
	struct stat path_info = { .st_mode = S_IFBLK | 0600,
				  .st_rdev = makedev(8U, 1U) };
	struct stat opened_info = path_info;
	struct stat partuuid_info = path_info;

	assert(format_identity_values_match(
		&expected, &path_info, &opened_info, &partuuid_info,
		expected.device_bytes, makedev(8U, 0U)));

	path_info.st_rdev = makedev(8U, 2U);
	assert(!format_identity_values_match(
		&expected, &path_info, &opened_info, &partuuid_info,
		expected.device_bytes, makedev(8U, 0U)));
	path_info = opened_info;

	opened_info.st_rdev = makedev(8U, 2U);
	assert(!format_identity_values_match(
		&expected, &path_info, &opened_info, &partuuid_info,
		expected.device_bytes, makedev(8U, 0U)));
	opened_info = path_info;

	partuuid_info.st_rdev = makedev(8U, 2U);
	assert(!format_identity_values_match(
		&expected, &path_info, &opened_info, &partuuid_info,
		expected.device_bytes, makedev(8U, 0U)));
	partuuid_info = path_info;

	assert(!format_identity_values_match(
		&expected, &path_info, &opened_info, &partuuid_info,
		expected.device_bytes - SWAPZ_SUPERBLOCK_BYTES, makedev(8U, 0U)));
	assert(!format_identity_values_match(
		&expected, &path_info, &opened_info, &partuuid_info,
		expected.device_bytes, makedev(8U, 16U)));

	opened_info.st_mode = S_IFREG | 0600;
	assert(!format_identity_values_match(
		&expected, &path_info, &opened_info, &partuuid_info,
		expected.device_bytes, makedev(8U, 0U)));
}

static void test_topology_flags_fail_closed(void)
{
	assert(format_topology_flags_allowed(1, 1, 1, 1, 1, 1, 1, 1, 1));
	assert(!format_topology_flags_allowed(0, 1, 1, 1, 1, 1, 1, 1, 1));
	assert(!format_topology_flags_allowed(1, 0, 1, 1, 1, 1, 1, 1, 1));
	assert(!format_topology_flags_allowed(1, 1, 0, 1, 1, 1, 1, 1, 1));
	assert(!format_topology_flags_allowed(1, 1, 1, 0, 1, 1, 1, 1, 1));
	assert(!format_topology_flags_allowed(1, 1, 1, 1, 0, 1, 1, 1, 1));
	assert(!format_topology_flags_allowed(1, 1, 1, 1, 1, 0, 1, 1, 1));
	assert(!format_topology_flags_allowed(1, 1, 1, 1, 1, 1, 0, 1, 1));
	assert(!format_topology_flags_allowed(1, 1, 1, 1, 1, 1, 1, 0, 1));
	assert(!format_topology_flags_allowed(1, 1, 1, 1, 1, 1, 1, 1, 0));
	assert(format_usb_transport_path(
		"/sys/devices/pci0000:00/usb1/1-2/host0/target0:0:0/0:0:0:0"));
	assert(!format_usb_transport_path(
		"/sys/devices/pci0000:00/ata1/host0/target0:0:0/0:0:0:0"));
	{
		char model[] = "Multi-Card   \n";
		char wrong_model[] = "Other\n";

		assert(format_observed_model_matches(model, "Multi-Card"));
		assert(!format_observed_model_matches(wrong_model, "Multi-Card"));
	}
}

static void test_mountinfo_device_parser(void)
{
	dev_t device = 0;
	unsigned int optional_fields = 0U;
	const char token[] = "rw";

	/* Invalid spans fail without undefined pointer arithmetic under UBSan. */
	assert(!format_mountinfo_optional_valid(NULL, token + 2U,
						 &optional_fields));
	assert(!format_mountinfo_optional_valid(token, NULL, &optional_fields));
	assert(!format_mountinfo_rw_options_valid(NULL, token + 2U));
	assert(!format_mountinfo_rw_options_valid(token, NULL));

	assert(format_mountinfo_line_device(
		"36 25 8:1 / /mnt rw,relatime - ext4 /dev/sda1 rw\n",
		&device) == 0);
	assert(device == makedev(8U, 1U));
	assert(format_mountinfo_line_device("36 25 bad / /mnt rw\n",
					    &device) < 0);
	assert(format_mountinfo_line_device("36 25 8:1\n", &device) < 0);
	assert(format_mountinfo_line_device(
		"036 25 8:2 / /other rw - ext4 /dev/sdb2 rw\n",
		&device) < 0);
	assert(format_mountinfo_line_device(
		"2147483648 25 8:2 / /other rw - ext4 /dev/sdb2 rw\n",
		&device) < 0);
	/*
	 * Pseudo-filesystem mounts (major zero) and filesystem-specific root
	 * tokens are normal. They must not reject unrelated host namespaces.
	 */
	assert(format_mountinfo_line_device(
		"36 25 0:20 / /proc rw - proc proc rw\n", &device) == 0);
	assert(device == makedev(0U, 20U));
	assert(!format_inventory_device_conflicts(device, makedev(8U, 1U),
						 makedev(8U, 0U)));
	assert(format_mountinfo_line_device(
		"37 25 0:0 / /tmp rw - tmpfs tmpfs rw\n", &device) == 0);
	assert(device == makedev(0U, 0U));
	assert(format_mountinfo_line_device(
		"38 25 0:4 net:[4026531840] /run/netns/example rw - nsfs nsfs rw\n",
		&device) == 0);
	assert(format_mountinfo_line_device(
		"36 25 0:4294967296 / /proc rw - proc proc rw\n",
		&device) < 0);
	assert(format_mountinfo_line_device(
		"36 25 -1:20 / /proc rw - proc proc rw\n", &device) < 0);

	/* An unrelated device cannot make an incomplete inventory harmless. */
	assert(format_mountinfo_line_device(
		"garbage 25 8:2 / /other rw - ext4 /dev/sda2 rw\n",
		&device) < 0);
	assert(format_mountinfo_line_device(
		"36 25 8:2 - ext4 /dev/sda2 rw\n", &device) < 0);
	assert(format_mountinfo_line_device(
		"36 25 8:2 / /other rw - ext4 /dev/sda2\n",
		&device) < 0);
	assert(format_mountinfo_line_device(
		"36 25 8:2 / /other rw - ext4 /dev/sda2 rw trailing\n",
		&device) < 0);

	assert(format_mountinfo_line_device(
		"36 25 8:2 / /other rw shared:7 - ext4 /dev/sda2 rw\n",
		&device) == 0);
	assert(format_mountinfo_line_device(
		"36 25 8:2 / /other ro,nosuid - ext4 /dev/sda2 ro,errors=remount-ro\n",
		&device) == 0);
	assert(format_mountinfo_line_device(
		"36 25 8:2 / /other invalid - ext4 /dev/sda2 rw\n",
		&device) < 0);
	assert(format_mountinfo_line_device(
		"36 25 8:2 / /other rw - ext4 /dev/sda2 invalid\n",
		&device) < 0);
	assert(format_mountinfo_line_device(
		"36 25 8:2 / /other rw shared:7 shared:8 - ext4 /dev/sda2 rw\n",
		&device) < 0);
	assert(format_mountinfo_line_device(
		"36 25 8:2 / /other rw shared: - ext4 /dev/sda2 rw\n",
		&device) < 0);
	assert(format_mountinfo_line_device(
		"36 25 8:2 / /other rw unbindable unbindable - ext4 /dev/sda2 rw\n",
		&device) < 0);
	assert(format_mountinfo_line_device(
		"36 25 8:2 / /other rw master:7 master:8 - ext4 /dev/sda2 rw\n",
		&device) < 0);
	assert(format_mountinfo_line_device(
		"36 25 8:2 / /other rw propagate_from:7 - ext4 /dev/sda2 rw\n",
		&device) < 0);
	assert(format_mountinfo_line_device(
		"36 25 8:2 / /other rw master:7 propagate_from:8 - ext4 /dev/sda2 rw\n",
		&device) == 0);
	/* Unknown optional fields are explicitly forward-compatible mountinfo. */
	assert(format_mountinfo_line_device(
		"36 25 8:2 / /other rw future:abc - ext4 /dev/sdb2 rw\n",
		&device) == 0);
	assert(format_mountinfo_line_device(
		"36 25 8:2 / /other\\040name rw shared:7 - ext4 /dev/sdb2 rw\n",
		&device) == 0);
	assert(format_mountinfo_line_device(
		"36 25 8:2 / /other\\9xx rw - ext4 /dev/sdb2 rw\n",
		&device) < 0);
	assert(format_mountinfo_line_device(
		"36 25 8:2 / /other\\000 rw - ext4 /dev/sdb2 rw\n",
		&device) < 0);
	assert(format_mountinfo_line_device(
		"36 25 8:2 / /other\\377 rw - ext4 /dev/sdb2 rw\n",
		&device) < 0);
	assert(format_mountinfo_line_device(
		"36 25 8:2 / /other\\011tab rw - ext4 /dev/sdb2 rw\n",
		&device) == 0);
	assert(format_mountinfo_line_device(
		"36 25 8:2 opaque-root relative rw - ext4 /dev/sdb2 rw\n",
		&device) < 0);
	assert(format_mountinfo_line_device(
		"36 25 8:2 / /other rw shared:garbage - ext4 /dev/sdb2 rw\n",
		&device) < 0);
	assert(format_mountinfo_line_device(
		"36 25 8:2 / /other rw shared:0 - ext4 /dev/sdb2 rw\n",
		&device) < 0);
	assert(format_mountinfo_line_device(
		"36 25 8:2 / /other rw mysterious:123 - ext4 /dev/sdb2 rw\n",
		&device) == 0);
}

static void test_mount_and_swap_identity_conflicts(void)
{
	dev_t device = makedev(8U, 1U);
	dev_t parent = makedev(8U, 0U);

	assert(format_inventory_device_conflicts(device, device, parent));
	assert(format_inventory_device_conflicts(parent, device, parent));
	assert(!format_inventory_device_conflicts(makedev(8U, 2U),
						  device, parent));
}

static void test_mountinfo_fixture_path(char path[PATH_MAX],
					const char *root, const char *relative)
{
	int length = snprintf(path, PATH_MAX, "%s/%s", root, relative);

	assert(length > 0 && (size_t)length < PATH_MAX);
}

static void test_mountinfo_fixture_write(const char *root,
					 const char *relative,
					 const char *contents)
{
	char path[PATH_MAX];
	FILE *stream;

	test_mountinfo_fixture_path(path, root, relative);
	stream = fopen(path, "w");
	assert(stream);
	assert(fputs(contents, stream) >= 0);
	assert(fclose(stream) == 0);
}

static void test_mounts_in_other_namespaces_refuse_formatting(void)
{
	char root[] = "/tmp/swapzctl-mountinfo-XXXXXX";
	char path[PATH_MAX];
	const dev_t device = makedev(8U, 1U);
	const dev_t parent = makedev(8U, 0U);

	/* No real mount, block device, or mount namespace is touched. */
	assert(mkdtemp(root));
	test_mountinfo_fixture_path(path, root, "self");
	assert(mkdir(path, 0700) == 0);
	test_mountinfo_fixture_path(path, root, "self/ns");
	assert(mkdir(path, 0700) == 0);
	test_mountinfo_fixture_path(path, root, "3031");
	assert(mkdir(path, 0700) == 0);
	test_mountinfo_fixture_path(path, root, "3031/ns");
	assert(mkdir(path, 0700) == 0);
	test_mountinfo_fixture_path(path, root, "self/root");
	assert(symlink("/", path) == 0);
	test_mountinfo_fixture_write(root, "self/ns/mnt", "self namespace\n");
	test_mountinfo_fixture_write(root, "3031/ns/mnt", "namespace\n");
	test_mountinfo_fixture_write(
		root, "self/mountinfo",
		"1 42 8:9 / / rw - ext4 /dev/root rw\n"
		"36 25 0:20 / /proc rw - proc proc rw\n");
	test_mountinfo_fixture_write(
		root, "3031/mountinfo",
		"37 25 8:1 / /card rw - ext4 /dev/sda1 rw\n");
	errno = 0;
	assert(format_mount_inventory_clear_from_proc(root, device, parent) < 0);
	assert(errno == EBUSY);

	/* The parent disk also conflicts, but a sibling does not. */
	test_mountinfo_fixture_write(
		root, "3031/mountinfo",
		"37 25 8:0 / /disk rw - ext4 /dev/sda rw\n");
	errno = 0;
	assert(format_mount_inventory_clear_from_proc(root, device, parent) < 0);
	assert(errno == EBUSY);
	test_mountinfo_fixture_write(
		root, "3031/mountinfo",
		"37 25 8:2 / /other rw - ext4 /dev/sda2 rw\n");
	assert(format_mount_inventory_clear_from_proc(root, device, parent) == 0);

	/* A readable but empty or truncated live inventory is not clearance. */
	test_mountinfo_fixture_write(
		root, "3031/mountinfo",
		"37 25 8:2 / /other rw - ext4 /dev/sda2\n");
	errno = 0;
	assert(format_mount_inventory_clear_from_proc(root, device, parent) < 0);
	assert(errno == EPROTO);
	test_mountinfo_fixture_write(root, "3031/mountinfo", "");
	errno = 0;
	assert(format_mount_inventory_clear_from_proc(root, device, parent) < 0);
	assert(errno == EPROTO);

	/* An empty chrooted peer view is redundant only in the same full-root ns. */
	test_mountinfo_fixture_path(path, root, "3031/ns/mnt");
	assert(unlink(path) == 0);
	assert(symlink("../../self/ns/mnt", path) == 0);
	assert(format_mount_inventory_clear_from_proc(root, device, parent) == 0);

	/* The coordinator's own selected-device mount remains visible to the gate. */
	test_mountinfo_fixture_write(
		root, "self/mountinfo",
		"1 42 8:9 / / rw - ext4 /dev/root rw\n"
		"2 1 8:1 / /card rw - ext4 /dev/sda1 rw\n"
		"36 25 0:20 / /proc rw - proc proc rw\n");
	errno = 0;
	assert(format_mount_inventory_clear_from_proc(root, device, parent) < 0);
	assert(errno == EBUSY);
	test_mountinfo_fixture_write(
		root, "self/mountinfo",
		"1 42 8:9 / / rw - ext4 /dev/root rw\n"
		"36 25 0:20 / /proc rw - proc proc rw\n");

	/* A chrooted coordinator cannot use the empty-peer shortcut. */
	test_mountinfo_fixture_path(path, root, "chroot");
	assert(mkdir(path, 0700) == 0);
	{
		char root_link[PATH_MAX];

		test_mountinfo_fixture_path(root_link, root, "self/root");
		assert(unlink(root_link) == 0);
		assert(symlink(path, root_link) == 0);
	}
	errno = 0;
	assert(format_mount_inventory_clear_from_proc(root, device, parent) < 0);
	assert(errno == EPROTO);
	test_mountinfo_fixture_path(path, root, "self/root");
	assert(unlink(path) == 0);
	assert(symlink("/", path) == 0);
	test_mountinfo_fixture_path(path, root, "chroot");
	assert(rmdir(path) == 0);

	/* Namespace replacement after the empty snapshot fails its second check. */
	{
		struct stat self_namespace;
		struct stat peer_namespace;

		test_mountinfo_fixture_path(path, root, "self/ns/mnt");
		assert(stat(path, &self_namespace) == 0);
		test_mountinfo_fixture_path(path, root, "3031/ns/mnt");
		assert(stat(path, &peer_namespace) == 0);
		assert(format_mount_namespace_identity_matches(
			&self_namespace, &peer_namespace));
		assert(unlink(path) == 0);
		test_mountinfo_fixture_write(root, "3031/ns/mnt",
					     "replacement namespace\n");
		errno = 0;
		assert(format_proc_empty_mountinfo_is_redundant(
			       root, "3031", &self_namespace,
			       &peer_namespace, 1) < 0);
		assert(errno == EPROTO);
		test_mountinfo_fixture_path(path, root, "3031/ns/mnt");
		assert(unlink(path) == 0);
		assert(symlink("../../self/ns/mnt", path) == 0);
	}

	test_mountinfo_fixture_write(
		root, "3031/mountinfo",
		"37 25 8:2 / /other rw - ext4 /dev/sda2 rw\n");
	test_mountinfo_fixture_write(root, "self/mountinfo", "");
	errno = 0;
	assert(format_mount_inventory_clear_from_proc(root, device, parent) < 0);
	assert(errno == EPROTO);
	test_mountinfo_fixture_write(
		root, "self/mountinfo",
		"1 42 8:9 / / rw - ext4 /dev/root rw\n"
		"36 25 0:20 / /proc rw - proc proc rw\n");

	/* Malformed or missing evidence for a live mount namespace still fails. */
	test_mountinfo_fixture_write(root, "3031/mountinfo", "invalid\n");
	errno = 0;
	assert(format_mount_inventory_clear_from_proc(root, device, parent) < 0);
	assert(errno == EPROTO);
	test_mountinfo_fixture_path(path, root, "3031/mountinfo");
	assert(unlink(path) == 0);
	errno = 0;
	assert(format_mount_inventory_clear_from_proc(root, device, parent) < 0);
	assert(errno == ENOENT);
	assert(format_mountinfo_open_failure_ignorable(
		       root, "3031", EINVAL) == 0);

	/*
	 * A task with no mount namespace cannot keep the selected storage mounted.
	 * Model the Linux zombie/exit race: the PID entry remains, mountinfo is
	 * unavailable, and ns/mnt is absent. Only known task-exit errors may pass.
	 */
	test_mountinfo_fixture_path(path, root, "3031/ns/mnt");
	assert(unlink(path) == 0);
	assert(format_mountinfo_open_failure_ignorable(
		       root, "3031", EINVAL) == 1);
	assert(format_mountinfo_open_failure_ignorable(
		       root, "3031", ENOENT) == 1);
	assert(format_mountinfo_open_failure_ignorable(
		       root, "3031", ESRCH) == 1);
	assert(format_mountinfo_open_failure_ignorable(
		       root, "3031", EACCES) == 0);
	assert(format_mount_inventory_clear_from_proc(root, device, parent) == 0);

	test_mountinfo_fixture_path(path, root, "self/mountinfo");
	assert(unlink(path) == 0);
	test_mountinfo_fixture_path(path, root, "self/root");
	assert(unlink(path) == 0);
	test_mountinfo_fixture_path(path, root, "self/ns/mnt");
	assert(unlink(path) == 0);
	test_mountinfo_fixture_path(path, root, "self/ns");
	assert(rmdir(path) == 0);
	test_mountinfo_fixture_path(path, root, "3031/ns");
	assert(rmdir(path) == 0);
	test_mountinfo_fixture_path(path, root, "3031");
	assert(rmdir(path) == 0);
	test_mountinfo_fixture_path(path, root, "self");
	assert(rmdir(path) == 0);
	assert(rmdir(root) == 0);
}

static FILE *test_swap_inventory_stream(const char *contents)
{
	FILE *stream = tmpfile();

	assert(stream);
	if (contents && *contents)
		assert(fputs(contents, stream) >= 0);
	rewind(stream);
	return stream;
}

static void test_swap_inventory_requires_complete_kernel_table(void)
{
	char swap_path[] = "/tmp/swapzctl-swapfile-XXXXXX";
	char inventory[PATH_MAX + 128U];
	struct stat info;
	FILE *stream;
	dev_t parent_device;
	int swap_fd;
	int length;

	swap_fd = mkstemp(swap_path);
	assert(swap_fd >= 0);
	assert(fstat(swap_fd, &info) == 0);
	parent_device = makedev(1U, 1U);
	if (parent_device == info.st_dev)
		parent_device = makedev(1U, 2U);

	stream = test_swap_inventory_stream("");
	errno = 0;
	assert(format_swap_inventory_stream_clear(stream, info.st_dev,
						  parent_device) < 0);
	assert(errno == EPROTO);
	assert(fclose(stream) == 0);

	stream = test_swap_inventory_stream(
		"Filename\t\t\t\tType\t\tSize\t\tUsed\t\tPriority\n");
	assert(format_swap_inventory_stream_clear(stream, info.st_dev,
						  parent_device) == 0);
	assert(fclose(stream) == 0);

	/* The kernel header grammar is literal, not merely five whitespace tokens. */
	stream = test_swap_inventory_stream(
		"Filename Type Size Used Priority\n");
	errno = 0;
	assert(format_swap_inventory_stream_clear(stream, info.st_dev,
						  parent_device) < 0);
	assert(errno == EPROTO);
	assert(fclose(stream) == 0);

	stream = test_swap_inventory_stream(
		"Filename Type Size Used\n");
	errno = 0;
	assert(format_swap_inventory_stream_clear(stream, info.st_dev,
						  parent_device) < 0);
	assert(errno == EPROTO);
	assert(fclose(stream) == 0);

	length = snprintf(inventory, sizeof(inventory), "%s file 1 0 -2\n",
			  swap_path);
	assert(length > 0 && (size_t)length < sizeof(inventory));
	stream = test_swap_inventory_stream(inventory);
	errno = 0;
	assert(format_swap_inventory_stream_clear(stream, info.st_dev,
						  parent_device) < 0);
	assert(errno == EPROTO);
	assert(fclose(stream) == 0);

	length = snprintf(
		inventory, sizeof(inventory),
		"Filename\t\t\t\tType\t\tSize\t\tUsed\t\tPriority\n%s file 1 0 -2\n",
		swap_path);
	assert(length > 0 && (size_t)length < sizeof(inventory));
	stream = test_swap_inventory_stream(inventory);
	errno = 0;
	assert(format_swap_inventory_stream_clear(stream, info.st_dev,
						  parent_device) < 0);
	assert(errno == EOPNOTSUPP);
	assert(fclose(stream) == 0);

	length = snprintf(
		inventory, sizeof(inventory),
		"Filename\t\t\t\tType\t\tSize\t\tUsed\t\tPriority\n%s partition 1 0 -2\n",
		swap_path);
	assert(length > 0 && (size_t)length < sizeof(inventory));
	stream = test_swap_inventory_stream(inventory);
	errno = 0;
	assert(format_swap_inventory_stream_clear(stream, info.st_dev,
						  parent_device) < 0);
	assert(errno == EOPNOTSUPP);
	assert(fclose(stream) == 0);

	assert(close(swap_fd) == 0);
	assert(unlink(swap_path) == 0);
}

/*
 * Exercise the real production parsers with byte-exact, rootless inventories.
 * No swapon, mount, device nodes or formatter writes are performed.
 */
static FILE *test_inventory_binary_stream(const void *bytes, size_t length)
{
	FILE *stream = tmpfile();

	assert(stream);
	assert(fwrite(bytes, 1U, length, stream) == length);
	rewind(stream);
	return stream;
}


/*
 * Inject production proc parsers into mock formatter gates. These ordinary
 * files represent namespace evidence; the mock write only changes memory.
 */
static int mock_inventory_verify(struct mock_format_context *context,
				 int final_gate)
{
	const dev_t selected_device = makedev(8U, 1U);
	const dev_t parent_device = makedev(8U, 0U);
	const char *swap_table = final_gate && context->late_swap_inventory ?
		context->late_swap_inventory : context->synthetic_swap_inventory;
	FILE *stream;
	int result;
	int saved_errno;

	if (context->synthetic_proc_root &&
	    format_mount_inventory_clear_from_proc(context->synthetic_proc_root,
						    selected_device, parent_device) < 0) {
		context->inventory_check = "mountinfo";
		goto failed;
	}
	if (!swap_table)
		return 0;
	stream = test_inventory_binary_stream(swap_table, strlen(swap_table));
	result = format_swap_inventory_stream_clear(stream, selected_device,
						    parent_device);
	saved_errno = errno;
	assert(fclose(stream) == 0);
	if (result < 0) {
		context->inventory_check = "/proc/swaps";
		errno = saved_errno;
		goto failed;
	}
	return 0;

failed:
	context->inventory_errno = errno;
	return -1;
}

static void test_mock_admission_refusal(const char *proc_root,
				      const char *swap_table, int expected_error)
{
	struct format_expectation expected = authorized_expectation();
	struct mock_format_context context = {
		.synthetic_proc_root = proc_root,
		.synthetic_swap_inventory = swap_table,
	};
	struct format_runtime_ops ops = mock_ops(&context);

	assert(format_device_with_ops("/synthetic/card", &expected, &ops) == 2);
	assert(context.inventory_errno == expected_error);
	assert(context.inventory_check != NULL);
	assert(!strcmp(context.inventory_check,
		       expected_error == EOPNOTSUPP ? "/proc/swaps" : "mountinfo"));
	assert(context.open_calls == 0U);
	assert(context.write_calls == 0U);
}

static void test_mountinfo_adversarial_inventory(void)
{
	static const char unrelated[] =
		"36 25 8:2 / /other rw - ext4 /dev/sdb2 rw\n";
	static const char duplicate[] =
		"36 25 8:2 / /other rw - ext4 /dev/sdb2 rw\n"
		"36 25 8:3 / /another rw - ext4 /dev/sdb3 rw\n";
	static const char embedded_nul[] =
		"36 25 8:2 / /other rw - ext4 /dev/sdb2 rw\n\0"
		"37 25 8:1 / /card rw - ext4 /dev/sda1 rw\n";
	static const char high_bytes[] =
		"36 25 8:2 /r\xc3\xa9 /mnt rw - ext4 /dev/sdb2 rw\n";
	static const char raw_control[] =
		"36 25 8:2 / /mnt\rname rw - ext4 /dev/sdb2 rw\n";
	const dev_t device = makedev(8U, 1U);
	const dev_t parent = makedev(8U, 0U);
	char oversized[SWAPZ_FORMAT_PROC_LINE_BYTES + 4U];
	FILE *stream;
	unsigned int state = 0x728b31f5U;

	stream = test_inventory_binary_stream(unrelated, sizeof(unrelated) - 1U);
	assert(format_mountinfo_stream_clear(stream, device, parent) == 0);
	assert(fclose(stream) == 0);
	stream = test_inventory_binary_stream(high_bytes, sizeof(high_bytes) - 1U);
	assert(format_mountinfo_stream_clear(stream, device, parent) == 0);
	assert(fclose(stream) == 0);
	/* Only NUL is impossible in a pathname; other raw filename bytes are legal. */
	stream = test_inventory_binary_stream(raw_control,
					     sizeof(raw_control) - 1U);
	assert(format_mountinfo_stream_clear(stream, device, parent) == 0);
	assert(fclose(stream) == 0);
	stream = test_inventory_binary_stream(duplicate, sizeof(duplicate) - 1U);
	errno = 0;
	assert(format_mountinfo_stream_clear(stream, device, parent) < 0);
	assert(errno == EPROTO);
	assert(fclose(stream) == 0);
	stream = test_inventory_binary_stream(embedded_nul,
					     sizeof(embedded_nul) - 1U);
	errno = 0;
	assert(format_mountinfo_stream_clear(stream, device, parent) < 0);
	assert(errno == EPROTO);
	assert(fclose(stream) == 0);
	stream = test_inventory_binary_stream(unrelated, sizeof(unrelated) - 2U);
	errno = 0;
	assert(format_mountinfo_stream_clear(stream, device, parent) < 0);
	assert(errno == EPROTO);
	assert(fclose(stream) == 0);
	memset(oversized, 'x', sizeof(oversized));
	oversized[sizeof(oversized) - 1U] = '\n';
	stream = test_inventory_binary_stream(oversized, sizeof(oversized));
	errno = 0;
	assert(format_mountinfo_stream_clear(stream, device, parent) < 0);
	assert(errno == EOVERFLOW);
	assert(fclose(stream) == 0);

	/* Deterministic bounded byte mutation: NUL can never hide a busy row. */
	for (unsigned int iteration = 0; iteration < 256U; ++iteration) {
		char mutated[sizeof(unrelated)];
		size_t index;

		memcpy(mutated, unrelated, sizeof(unrelated) - 1U);
		state ^= state << 13;
		state ^= state >> 17;
		state ^= state << 5;
		index = state % (sizeof(unrelated) - 1U);
		mutated[index] = '\0';
		stream = test_inventory_binary_stream(mutated,
						       sizeof(unrelated) - 1U);
		assert(format_mountinfo_stream_clear(stream, device,
							     parent) < 0);
		assert(fclose(stream) == 0);
	}
}

static void test_swap_adversarial_inventory(void)
{
	static const char header[] =
		"Filename\t\t\t\tType\t\tSize\t\tUsed\t\tPriority\n";
	char file_path[] = "/tmp/swapzctl-unrelated-XXXXXX";
	char second_path[] = "/tmp/swapzctl-second-XXXXXX";
	char alias_path[] = "/tmp/swapzctl-same-inode-XXXXXX";
	char inventory[PATH_MAX + 256U];
	char duplicate[2U * PATH_MAX + 256U];
	struct stat info;
	struct stat other_info;
	dev_t device = makedev(8U, 1U);
	dev_t parent = makedev(8U, 0U);
	unsigned int state = 0x9e3779b9U;
	FILE *stream;
	int fd;
	int second_fd;
	int alias_fd;
	int length;
	char parsed_path[PATH_MAX];
	int block_entry;

	fd = mkstemp(file_path);
	assert(fd >= 0);
	assert(fstat(fd, &info) == 0);
	if (info.st_dev == device)
		device = makedev(8U, 3U);
	if (info.st_dev == parent)
		parent = makedev(8U, 4U);
	length = snprintf(inventory, sizeof(inventory),
			  "%s%s file 1 0 -2\n", header, file_path);
	assert(length > 0 && (size_t)length < sizeof(inventory));
	stream = test_inventory_binary_stream(inventory, (size_t)length);
	errno = 0;
	assert(format_swap_inventory_stream_clear(stream, device, parent) < 0);
	assert(errno == EOPNOTSUPP);
	assert(fclose(stream) == 0);
	/* Distinct local inodes cannot authenticate foreign swap entries. */
	second_fd = mkstemp(second_path);
	assert(second_fd >= 0);
	assert(fstat(second_fd, &other_info) == 0);
	assert(other_info.st_dev == info.st_dev);
	assert(other_info.st_ino != info.st_ino);
	length = snprintf(duplicate, sizeof(duplicate),
			  "%s%s file 1 0 -2\n%s file 1 0 -3\n",
			  header, file_path, second_path);
	assert(length > 0 && (size_t)length < sizeof(duplicate));
	stream = test_inventory_binary_stream(duplicate, (size_t)length);
	errno = 0;
	assert(format_swap_inventory_stream_clear(stream, device, parent) < 0);
	assert(errno == EOPNOTSUPP);
	assert(fclose(stream) == 0);

	/* Hard-link aliases cannot authenticate a foreign active inode. */
	alias_fd = mkstemp(alias_path);
	assert(alias_fd >= 0);
	assert(close(alias_fd) == 0);
	assert(unlink(alias_path) == 0);
	assert(link(file_path, alias_path) == 0);
	length = snprintf(duplicate, sizeof(duplicate),
			  "%s%s file 1 0 -2\n%s file 1 0 -3\n",
			  header, file_path, alias_path);
	assert(length > 0 && (size_t)length < sizeof(duplicate));
	stream = test_inventory_binary_stream(duplicate, (size_t)length);
	errno = 0;
	assert(format_swap_inventory_stream_clear(stream, device, parent) < 0);
	assert(errno == EOPNOTSUPP);
	assert(fclose(stream) == 0);
	assert(unlink(alias_path) == 0);
	/*
	 * A pathname substituted with a symlink after swapon is not trusted:
	 * the active kernel object was not the symlink target we would follow now.
	 */
	assert(symlink(file_path, alias_path) == 0);
	length = snprintf(duplicate, sizeof(duplicate),
			  "%s%s file 1 0 -3\n", header, alias_path);
	assert(length > 0 && (size_t)length < sizeof(duplicate));
	stream = test_inventory_binary_stream(duplicate, (size_t)length);
	errno = 0;
	assert(format_swap_inventory_stream_clear(stream, device, parent) < 0);
	assert(errno == EOPNOTSUPP);
	assert(fclose(stream) == 0);
	assert(unlink(alias_path) == 0);
	assert(close(second_fd) == 0);
	assert(unlink(second_path) == 0);
	length = snprintf(duplicate, sizeof(duplicate),
			  "%s%s file 1 0 -2\n%s file 1 0 -2\n",
			  header, file_path, file_path);
	assert(length > 0 && (size_t)length < sizeof(duplicate));
	stream = test_inventory_binary_stream(duplicate, (size_t)length);
	errno = 0;
	assert(format_swap_inventory_stream_clear(stream, device, parent) < 0);
	assert(errno == EOPNOTSUPP);
	assert(fclose(stream) == 0);
	stream = test_inventory_binary_stream(inventory,
					     strlen(inventory) - 1U);
	errno = 0;
	assert(format_swap_inventory_stream_clear(stream, device, parent) < 0);
	assert(errno == EPROTO);
	assert(fclose(stream) == 0);
	assert(format_swap_inventory_entry_parse(
		       "/tmp/\xc3\xa9 file 1 0 -2\n", parsed_path,
		       &block_entry) == 0);
	assert(!block_entry);
	assert(!strcmp(parsed_path, "/tmp/\xc3\xa9"));
	assert(format_swap_inventory_entry_parse(
		       "/tmp/swap\\040file file 1 0 -2\n", parsed_path,
		       &block_entry) == 0);
	assert(!strcmp(parsed_path, "/tmp/swap file"));
	assert(format_swap_inventory_entry_parse(
		       "/tmp/swap\\134name file 1 0 -2\n", parsed_path,
		       &block_entry) == 0);
	assert(!strcmp(parsed_path, "/tmp/swap\\name"));
	assert(format_swap_inventory_entry_parse(
		       "/tmp/swap\\011name file 1 0 -2\n", parsed_path,
		       &block_entry) == 0);
	assert(!strcmp(parsed_path, "/tmp/swap\tname"));
	assert(format_swap_inventory_entry_parse(
		       "/tmp/swap\\012name file 1 0 -2\n", parsed_path,
		       &block_entry) == 0);
	assert(!strcmp(parsed_path, "/tmp/swap\nname"));
	assert(format_swap_inventory_entry_parse(
		       "/tmp/swap\rname file 1 0 -2\n", parsed_path,
		       &block_entry) == 0);
	assert(!strcmp(parsed_path, "/tmp/swap\rname"));

	/* Unknown row types, invalid sizes, priorities and missing columns fail. */
	static const char *const malformed_rows[] = {
		"/tmp/file unknown 1 0 -2\n",
		"/tmp/file file 0 0 -2\n",
		"/tmp/file file 1 2 -2\n",
		"/tmp/file file -1 0 -2\n",
		"/tmp/file file 1 0 +2\n",
		"/tmp/file file 1 0 -0\n",
		"/tmp/file file 01 0 -2\n",
		"/tmp/file file 1 00 -2\n",
		"/tmp/file file 1 0 -02\n",
		"/tmp/swap\\000name file 1 0 -2\n",
		"/tmp/swap\\777name file 1 0 -2\n",
		"/tmp/swap\\9xx file 1 0 -2\n",
		"/tmp/file file 18446744073709551616 0 -2\n",
		"/tmp/file file 1 0 -2147483649\n",
		"/tmp/file file 1 0 2147483648\n",
		"/tmp/file file 1 0\n",
		"relative file 1 0 -2\n",
	};
	for (size_t index = 0;
	     index < sizeof(malformed_rows) / sizeof(malformed_rows[0]);
	     ++index)
		assert(format_swap_inventory_entry_parse(
			       malformed_rows[index], parsed_path, &block_entry) < 0);
	assert(format_swap_inventory_entry_parse(
		       "/tmp/file file 1 0 2147483647\n", parsed_path,
		       &block_entry) == 0);
	assert(format_swap_inventory_entry_parse(
		       "/tmp/file file 1 0 -2147483648\n", parsed_path,
		       &block_entry) == 0);

	for (unsigned int iteration = 0; iteration < 256U; ++iteration) {
		char mutated[sizeof(inventory)];
		size_t index;

		memcpy(mutated, inventory, strlen(inventory));
		state ^= state << 13;
		state ^= state >> 17;
		state ^= state << 5;
		index = state % strlen(inventory);
		mutated[index] = '\0';
		stream = test_inventory_binary_stream(mutated,
						       strlen(inventory));
		assert(format_swap_inventory_stream_clear(stream, device,
								     parent) < 0);
		assert(fclose(stream) == 0);
	}

	/* Later malformed records take precedence over active-row ambiguity. */
	{
		static const char invalid_after_active[] =
			"Filename\t\t\t\tType\t\tSize\t\tUsed\t\tPriority\n"
			"/tmp/foreign file 1 0 -2\n"
			"/tmp/foreign file 1 0\n";

		stream = test_inventory_binary_stream(invalid_after_active,
						       sizeof(invalid_after_active) - 1U);
		errno = 0;
		assert(format_swap_inventory_stream_clear(stream, device, parent) < 0);
		assert(errno == EPROTO);
		assert(fclose(stream) == 0);
	}
	/* The row count remains explicitly bounded without allocating identities. */
	{
		stream = tmpfile();
		assert(stream);
		assert(fputs(header, stream) >= 0);
		for (size_t row = 0; row <= SWAPZ_FORMAT_PROC_MAX_ROWS; ++row)
			assert(fputs("/tmp/foreign file 1 0 -2\n", stream) >= 0);
		assert(fseek(stream, 0L, SEEK_SET) == 0);
		errno = 0;
		assert(format_swap_inventory_stream_clear(stream, device, parent) < 0);
		assert(errno == EOVERFLOW);
		assert(fclose(stream) == 0);
	}

	/*
	 * An unrelated active swapfile name is emitted escaped by the kernel.
	 * Decode the exact grammar, but local stat cannot grant clearance.
	 */
	{
		char directory[] = "/tmp/swapzctl-escaped-XXXXXX";
		char spaced_path[PATH_MAX];
		char encoded_path[PATH_MAX + 16U];
		int spaced_fd;

		assert(mkdtemp(directory));
		assert(snprintf(spaced_path, sizeof(spaced_path), "%s/swap file",
				directory) > 0);
		spaced_fd = open(spaced_path, O_CREAT | O_EXCL | O_RDWR, 0600);
		assert(spaced_fd >= 0);
		assert(snprintf(encoded_path, sizeof(encoded_path), "%s/swap\\040file",
				directory) > 0);
		length = snprintf(inventory, sizeof(inventory),
				  "%s%s file 1 0 -2\n", header, encoded_path);
		assert(length > 0 && (size_t)length < sizeof(inventory));
		stream = test_inventory_binary_stream(inventory, (size_t)length);
		errno = 0;
		assert(format_swap_inventory_stream_clear(stream, device, parent) < 0);
		assert(errno == EOPNOTSUPP);
		assert(fclose(stream) == 0);
		assert(close(spaced_fd) == 0);
		assert(unlink(spaced_path) == 0);
		assert(rmdir(directory) == 0);
	}

	/* Byte and row budgets are checked without allocating enormous fixtures. */
	{
		char bounded_line[4];
		size_t bytes_read = SWAPZ_FORMAT_PROC_MAX_BYTES - 1U;
		size_t count = SWAPZ_FORMAT_PROC_MAX_ROWS;
		size_t capacity = 0;
		void *entries = NULL;
		unsigned long long identifier = 7ULL;

		stream = test_inventory_binary_stream("a\n", 2U);
		errno = 0;
		assert(format_inventory_read_line(stream, bounded_line,
						   sizeof(bounded_line),
						   &bytes_read) < 0);
		assert(errno == EOVERFLOW);
		assert(fclose(stream) == 0);
		errno = 0;
		assert(format_inventory_append(&entries, &count, &capacity,
						 &identifier, sizeof(identifier)) < 0);
		assert(errno == EOVERFLOW);
		assert(entries == NULL);
	}
	/* A sysfs attribute with an embedded NUL cannot pass text validation. */
	assert(lseek(fd, 0, SEEK_SET) == 0);
	assert(write(fd, "1\0\n", 3U) == 3);
	errno = 0;
	assert(format_read_text_file(file_path, parsed_path,
					     sizeof(parsed_path)) < 0);
	assert(errno == EPROTO);
	assert(close(fd) == 0);
	assert(unlink(file_path) == 0);
}


/*
 * Fake /proc mount tables represent other namespaces without unshare,
 * swapon, mounts or device nodes. Each uncertain condition must refuse
 * before the only mocked formatter write callback.
 */
static void test_namespace_swap_ambiguity_never_writes(void)
{
	static const char swap_header[] =
		"Filename\t\t\t\tType\t\tSize\t\tUsed\t\tPriority\n";
	static const char sibling_mount[] =
		"37 25 8:2 / /sibling rw future:opaque - ext4 /dev/sibling rw\n";
	static const char *const busy_mounts[] = {
		"37 25 8:1 / /selected rw - ext4 /dev/selected rw\n",
		"37 25 8:0 / /parent rw - ext4 /dev/parent rw\n",
	};
	struct format_expectation expected = authorized_expectation();
	char proc_root[] = "/tmp/swapzctl-foreign-proc-XXXXXX";
	char swap_path[] = "/tmp/swapzctl-foreign-swap-XXXXXX";
	char retired_path[PATH_MAX];
	char late_retired_path[PATH_MAX];
	char inventory[PATH_MAX + 128U];
	char duplicate[2U * PATH_MAX + 128U];
	char path[PATH_MAX];
	struct stat original_info;
	struct stat replacement_info;
	struct stat retired_info;
	int file_descriptor;
	int length;

	assert(mkdtemp(proc_root));
	test_mountinfo_fixture_path(path, proc_root, "self");
	assert(mkdir(path, 0700) == 0);
	test_mountinfo_fixture_path(path, proc_root, "self/ns");
	assert(mkdir(path, 0700) == 0);
	test_mountinfo_fixture_path(path, proc_root, "3031");
	assert(mkdir(path, 0700) == 0);
	test_mountinfo_fixture_path(path, proc_root, "3031/ns");
	assert(mkdir(path, 0700) == 0);
	test_mountinfo_fixture_path(path, proc_root, "self/root");
	assert(symlink("/", path) == 0);
	test_mountinfo_fixture_write(proc_root, "self/ns/mnt",
				     "self namespace\n");
	test_mountinfo_fixture_write(proc_root, "3031/ns/mnt", "namespace\n");
	test_mountinfo_fixture_write(proc_root, "self/mountinfo",
		"1 42 8:9 / / rw - ext4 /dev/root rw\n"
		"36 25 0:20 / /proc rw unknown:opaque - proc proc rw\n");

	for (size_t index = 0;
	     index < sizeof(busy_mounts) / sizeof(busy_mounts[0]); ++index) {
		test_mountinfo_fixture_write(proc_root, "3031/mountinfo",
					     busy_mounts[index]);
		test_mock_admission_refusal(proc_root, swap_header, EBUSY);
	}

	/* Unknown optional fields are legal, and unrelated sibling mounts clear. */
	test_mountinfo_fixture_write(proc_root, "3031/mountinfo", sibling_mount);
	{
		struct mock_format_context context = {
			.synthetic_proc_root = proc_root,
			.synthetic_swap_inventory = swap_header,
		};
		struct format_runtime_ops ops = mock_ops(&context);

		assert(format_device_with_ops("/synthetic/card", &expected,
					      &ops) == 0);
		assert(context.write_calls == 1U); /* In-memory callback only. */
	}

	/*
	 * An inaccessible live /proc/PID/mountinfo must fail through the
	 * formatter gate with zero writes. Inject EACCES instead of chmod(000)
	 * so this remains deterministic even when the native suite runs as root.
	 */
	test_mountinfo_fixture_path(path, proc_root, "3031/mountinfo");
	test_fopen_denied_path = path;
	test_mock_admission_refusal(proc_root, swap_header, EACCES);
	test_fopen_denied_path = NULL;

	/* Missing live /proc/PID/mountinfo and malformed rows fail closed too. */
	assert(unlink(path) == 0);
	test_mock_admission_refusal(proc_root, swap_header, ENOENT);
	test_mountinfo_fixture_write(proc_root, "3031/mountinfo",
		"37 25 8:2 / /sibling rw - ext4 /dev/sibling\n");
	test_mock_admission_refusal(proc_root, swap_header, EPROTO);
	test_mountinfo_fixture_write(proc_root, "3031/mountinfo", sibling_mount);
	/* Device-node pathnames also lack authenticated /proc/swaps dev_t. */
	{
		static const char *const partition_rows[] = {
			"/dev/selected partition 1 0 -2\n",
			"/dev/parent partition 1 0 -2\n",
			"/dev/sibling partition 1 0 -2\n",
		};

		for (size_t index = 0;
		     index < sizeof(partition_rows) / sizeof(partition_rows[0]);
		     ++index) {
			length = snprintf(inventory, sizeof(inventory), "%s%s",
					  swap_header, partition_rows[index]);
			assert(length > 0 && (size_t)length < sizeof(inventory));
			test_mock_admission_refusal(proc_root, inventory, EOPNOTSUPP);
		}
	}

	/*
	 * Foreign namespace: kernel still refers to inode A, but the reported
	 * pathname now resolves locally to inode B on the same local filesystem.
	 */
	file_descriptor = mkstemp(swap_path);
	assert(file_descriptor >= 0);
	assert(fstat(file_descriptor, &original_info) == 0);
	assert(close(file_descriptor) == 0);
	length = snprintf(retired_path, sizeof(retired_path), "%s.old", swap_path);
	assert(length > 0 && (size_t)length < sizeof(retired_path));
	assert(rename(swap_path, retired_path) == 0);
	file_descriptor = open(swap_path,
			       O_CREAT | O_EXCL | O_WRONLY | O_CLOEXEC, 0600);
	assert(file_descriptor >= 0);
	assert(fstat(file_descriptor, &replacement_info) == 0);
	assert(close(file_descriptor) == 0);
	assert(replacement_info.st_dev == original_info.st_dev);
	assert(replacement_info.st_ino != original_info.st_ino);
	length = snprintf(inventory, sizeof(inventory),
			  "%s%s file 1 0 -2\n", swap_header, swap_path);
	assert(length > 0 && (size_t)length < sizeof(inventory));
	test_mock_admission_refusal(proc_root, inventory, EOPNOTSUPP);

	/* Missing file, final-component symlink, and inode alias also refuse. */
	assert(unlink(swap_path) == 0);
	test_mock_admission_refusal(proc_root, inventory, EOPNOTSUPP);
	assert(symlink(retired_path, swap_path) == 0);
	test_mock_admission_refusal(proc_root, inventory, EOPNOTSUPP);
	assert(unlink(swap_path) == 0);
	assert(link(retired_path, swap_path) == 0);
	length = snprintf(duplicate, sizeof(duplicate),
			  "%s%s file 1 0 -2\n%s file 1 0 -3\n",
			  swap_header, swap_path, retired_path);
	assert(length > 0 && (size_t)length < sizeof(duplicate));
	test_mock_admission_refusal(proc_root, duplicate, EOPNOTSUPP);
	assert(unlink(swap_path) == 0);

	/* An initially empty snapshot may become busy before final write gate. */
	file_descriptor = open(swap_path,
			       O_CREAT | O_EXCL | O_WRONLY | O_CLOEXEC, 0600);
	assert(file_descriptor >= 0);
	assert(fstat(file_descriptor, &original_info) == 0);
	assert(close(file_descriptor) == 0);
	length = snprintf(late_retired_path, sizeof(late_retired_path),
			  "%s.late", swap_path);
	assert(length > 0 && (size_t)length < sizeof(late_retired_path));
	{
		struct mock_format_context context = {
			.synthetic_proc_root = proc_root,
			.synthetic_swap_inventory = swap_header,
			.late_swap_inventory = inventory,
			.replacement_path = swap_path,
			.retired_path = late_retired_path,
		};
		struct format_runtime_ops ops = mock_ops(&context);

		assert(format_device_with_ops("/synthetic/card", &expected,
					      &ops) == 2);
		assert(context.preopen_calls == 1U);
		assert(context.verify_calls == 2U);
		assert(context.read_calls == 1U);
		assert(context.replacement_calls == 1U);
		assert(context.inventory_errno == EOPNOTSUPP);
		assert(context.inventory_check != NULL);
		assert(!strcmp(context.inventory_check, "/proc/swaps"));
		assert(context.write_calls == 0U);
	}
	assert(lstat(swap_path, &replacement_info) == 0);
	assert(lstat(late_retired_path, &retired_info) == 0);
	assert(replacement_info.st_ino != original_info.st_ino);
	assert(retired_info.st_ino == original_info.st_ino);

	assert(unlink(swap_path) == 0);
	assert(unlink(late_retired_path) == 0);
	assert(unlink(retired_path) == 0);
	test_mountinfo_fixture_path(path, proc_root, "3031/mountinfo");
	assert(unlink(path) == 0);
	test_mountinfo_fixture_path(path, proc_root, "3031/ns/mnt");
	assert(unlink(path) == 0);
	test_mountinfo_fixture_path(path, proc_root, "3031/ns");
	assert(rmdir(path) == 0);
	test_mountinfo_fixture_path(path, proc_root, "3031");
	assert(rmdir(path) == 0);
	test_mountinfo_fixture_path(path, proc_root, "self/mountinfo");
	assert(unlink(path) == 0);
	test_mountinfo_fixture_path(path, proc_root, "self/root");
	assert(unlink(path) == 0);
	test_mountinfo_fixture_path(path, proc_root, "self/ns/mnt");
	assert(unlink(path) == 0);
	test_mountinfo_fixture_path(path, proc_root, "self/ns");
	assert(rmdir(path) == 0);
	test_mountinfo_fixture_path(path, proc_root, "self");
	assert(rmdir(path) == 0);
	assert(rmdir(proc_root) == 0);
}

static void test_formatter_path_admission(void)
{
	struct format_expectation expected = authorized_expectation();
	struct stat path_info = {
		.st_mode = S_IFBLK | 0600, .st_rdev = makedev(8U, 1U),
		.st_dev = makedev(0U, 7U), .st_ino = 17U,
	};
	struct stat opened_info = path_info;
	struct stat partuuid_info = path_info;
	char regular[] = "/tmp/swapzctl-nofollow-XXXXXX";
	char alias[sizeof(regular) + 8U];
	int fd;

	assert(format_identity_values_match(&expected, &path_info, &opened_info,
						  &partuuid_info,
						  expected.device_bytes,
						  makedev(8U, 0U)));
	opened_info.st_ino++;
	assert(!format_identity_values_match(&expected, &path_info, &opened_info,
						   &partuuid_info,
						   expected.device_bytes,
						   makedev(8U, 0U)));
	opened_info = path_info;
	path_info.st_uid = 42U;
	assert(!format_identity_values_match(&expected, &path_info, &opened_info,
						   &partuuid_info,
						   expected.device_bytes,
						   makedev(8U, 0U)));
	path_info = opened_info;
	path_info.st_mode |= S_IWOTH;
	assert(!format_identity_values_match(&expected, &path_info, &opened_info,
						   &partuuid_info,
						   expected.device_bytes,
						   makedev(8U, 0U)));

	fd = mkstemp(regular);
	assert(fd >= 0);
	assert(snprintf(alias, sizeof(alias), "%s.link", regular) > 0);
	assert(symlink(regular, alias) == 0);
	errno = 0;
	assert(format_default_open_device(NULL, alias) < 0);
	assert(errno == ELOOP);
	assert(unlink(alias) == 0);
	assert(close(fd) == 0);
	assert(unlink(regular) == 0);
}

static void test_superblock_validation_and_reserved_bytes(void)
{
	struct format_expectation expected = authorized_expectation();
	unsigned char header[SWAPZ_SUPERBLOCK_BYTES];

	make_valid_header(header, expected.device_bytes);
	assert(swapz_sb_valid(header, expected.device_bytes));
	header[SWAPZ_SUPERBLOCK_RESERVED_OFFSET] = 1U;
	assert(!swapz_sb_valid(header, expected.device_bytes));
	header[SWAPZ_SUPERBLOCK_RESERVED_OFFSET] = 0U;
	memset(header + SWAPZ_SUPERBLOCK_UUID_OFFSET, 0,
	       SWAPZ_SUPERBLOCK_UUID_BYTES);
	assert(!swapz_sb_valid(header, expected.device_bytes));
	make_valid_header(header, expected.device_bytes);
	assert(!swapz_sb_valid(header,
			       expected.device_bytes - SWAPZ_SUPERBLOCK_BYTES));
}

static void test_unbound_cli_is_blocked_before_io(void)
{
	char *unbound[] = { "swapzctl", "format", "/dev/anything" };
	char *old_bound[] = {
		"swapzctl", "format", "/dev/anything",
		"--expect-major-minor", "8:1",
		"--expect-bytes", "124787884032",
	};

	assert(swapzctl_program_main(3, unbound) == 2);
	assert(swapzctl_program_main(7, old_bound) == 2);
}

static void test_protected_selector_is_mandatory(void)
{
	struct format_expectation expected = authorized_expectation();
	struct mock_format_context context = {
		.authorization_errors = { EPERM },
		.authorization_error_count = 1U,
	};
	struct format_runtime_ops ops = mock_ops(&context);

	assert(format_default_authorized_target_verify(NULL, &expected) == 0);
	test_configured_partuuid = "deadbeef-01";
	errno = 0;
	assert(format_default_authorized_target_verify(NULL, &expected) < 0);
	assert(errno == EPERM);
	test_configured_partuuid = NULL;
	errno = 0;
	assert(format_default_authorized_target_verify(NULL, &expected) < 0);
	assert(errno == ENOENT);
	test_configured_partuuid = "f13428f6-01";
	test_config_error = EACCES;
	errno = 0;
	assert(format_default_authorized_target_verify(NULL, &expected) < 0);
	assert(errno == EACCES);
	test_config_error = 0;

	/* An absent or mismatched selector cannot even open media. */
	assert(format_device_with_ops("/synthetic/card", &expected, &ops) == 2);
	assert(context.authorization_calls == 1U);
	assert(context.preopen_calls == 0U);
	assert(context.open_calls == 0U);
	assert(context.write_calls == 0U);
}

static void test_selector_revocation_before_write_refuses(void)
{
	struct format_expectation expected = authorized_expectation();
	struct mock_format_context context = {
		.authorization_errors = { 0, 0, EPERM },
		.authorization_error_count = 3U,
	};
	struct format_runtime_ops ops = mock_ops(&context);

	assert(format_device_with_ops("/synthetic/card", &expected, &ops) == 2);
	assert(context.authorization_calls == 3U);
	assert(context.preopen_calls == 1U);
	assert(context.verify_calls == 1U);
	assert(context.read_calls == 1U);
	assert(context.write_calls == 0U);
	assert(context.close_calls == 1U);
}

static void test_partial_header_write_is_not_resumed(void)
{
	unsigned char header[SWAPZ_SUPERBLOCK_BYTES] = {0};
	FILE *file = tmpfile();
	int fd;

	assert(file != NULL);
	fd = fileno(file);
	assert(fd >= 0);
	test_pwrite_calls = 0;
	test_pwrite_short = 1;
	errno = 0;
	assert(exact_io(fd, header, sizeof(header), 1) < 0);
	assert(errno == EIO);
	assert(test_pwrite_calls == 1U);
	test_pwrite_short = 0;
	assert(fclose(file) == 0);
}

static void test_preopen_permission_refuses_before_open_or_write(void)
{
	struct format_expectation expected = authorized_expectation();
	struct mock_format_context context = { .preopen_error = EACCES };
	struct format_runtime_ops ops = mock_ops(&context);

	assert(format_device_with_ops("/synthetic/card", &expected, &ops) == 2);
	assert(context.preopen_calls == 1U);
	assert(context.open_calls == 0U);
	assert(context.read_calls == 0U);
	assert(context.write_calls == 0U);
	assert(context.close_calls == 0U);
}

static void test_wrong_opened_device_refuses_before_read_or_write(void)
{
	struct format_expectation expected = authorized_expectation();
	struct mock_format_context context = {
		.verify_errors = { ESTALE },
		.verify_error_count = 1U,
	};
	struct format_runtime_ops ops = mock_ops(&context);

	assert(format_device_with_ops("/synthetic/card", &expected, &ops) == 2);
	assert(context.open_calls == 1U);
	assert(context.verify_calls == 1U);
	assert(context.read_calls == 0U);
	assert(context.write_calls == 0U);
	assert(context.close_calls == 1U);
}

static void test_invalid_header_refuses_without_write(void)
{
	struct format_expectation expected = authorized_expectation();
	struct mock_format_context context = {0};
	struct format_runtime_ops ops = mock_ops(&context);

	make_valid_header(context.media, expected.device_bytes);
	context.media[SWAPZ_SUPERBLOCK_RESERVED_OFFSET] = 1U;
	assert(format_device_with_ops("/synthetic/card", &expected, &ops) == 2);
	assert(context.read_calls == 1U);
	assert(context.write_calls == 0U);
	assert(context.sync_calls == 0U);
	assert(context.close_calls == 1U);
}

static void test_stale_identity_refuses_at_last_prewrite_gate(void)
{
	struct format_expectation expected = authorized_expectation();
	struct mock_format_context context = {
		.verify_errors = { 0, ESTALE },
		.verify_error_count = 2U,
	};
	struct format_runtime_ops ops = mock_ops(&context);

	assert(format_device_with_ops("/synthetic/card", &expected, &ops) == 2);
	assert(context.read_calls == 1U);
	assert(context.random_calls == 1U);
	assert(context.verify_calls == 2U);
	assert(context.write_calls == 0U);
	assert(context.sync_calls == 0U);
	assert(context.close_calls == 1U);
}

static void test_device_disappearance_before_write_refuses(void)
{
	struct format_expectation expected = authorized_expectation();
	struct mock_format_context context = {
		.verify_errors = { 0, ENODEV },
		.verify_error_count = 2U,
	};
	struct format_runtime_ops ops = mock_ops(&context);

	assert(format_device_with_ops("/synthetic/card", &expected, &ops) == 2);
	assert(context.write_calls == 0U);
	assert(context.close_calls == 1U);
}

static void test_inventory_gate_errors_never_reach_header_write(void)
{
	static const int inventory_errors[] = {
		EPROTO, EOVERFLOW, EBUSY, EACCES,
	};
	struct format_expectation expected = authorized_expectation();

	for (size_t index = 0;
	     index < sizeof(inventory_errors) / sizeof(inventory_errors[0]);
	     ++index) {
		struct mock_format_context preopen = {
			.preopen_error = inventory_errors[index],
		};
		struct format_runtime_ops preopen_ops = mock_ops(&preopen);
		struct mock_format_context recheck = {
			.verify_errors = { 0 },
			.verify_error_count = 2U,
		};
		struct format_runtime_ops recheck_ops = mock_ops(&recheck);

		/* Even a late discovered mount/swap/parse ambiguity is no-write. */
		recheck.verify_errors[1] = inventory_errors[index];
		assert(format_device_with_ops("/synthetic/card", &expected,
					      &preopen_ops) == 2);
		assert(preopen.open_calls == 0U);
		assert(preopen.write_calls == 0U);
		assert(format_device_with_ops("/synthetic/card", &expected,
					      &recheck_ops) == 2);
		assert(recheck.read_calls == 1U);
		assert(recheck.random_calls == 1U);
		assert(recheck.write_calls == 0U);
		assert(recheck.sync_calls == 0U);
	}
}

static void test_read_only_transition_before_write_refuses(void)
{
	struct format_expectation expected = authorized_expectation();
	struct mock_format_context context = {
		.verify_errors = { 0, EROFS },
		.verify_error_count = 2U,
	};
	struct format_runtime_ops ops = mock_ops(&context);

	assert(format_device_with_ops("/synthetic/card", &expected, &ops) == 2);
	assert(context.read_calls == 1U);
	assert(context.write_calls == 0U);
	assert(context.sync_calls == 0U);
	assert(context.close_calls == 1U);
}

/* A secondary close failure and diagnostic output must not replace errno. */
static void test_formatter_originating_errno_survives_diagnostics_and_close(void)
{
	struct format_expectation expected = authorized_expectation();
	struct mock_format_context fixtures[] = {
		{ .authorization_errors = { EPERM },
		  .authorization_error_count = 1U },
		{ .preopen_error = EBUSY },
		{ .open_error = EACCES },
		{ .verify_errors = { ESTALE }, .verify_error_count = 1U,
		  .close_error = EOVERFLOW },
		{ .read_error = EIO, .close_error = EOVERFLOW },
		{ .random_error = EAGAIN, .close_error = EOVERFLOW },
		{ .verify_errors = { 0, ESTALE }, .verify_error_count = 2U,
		  .close_error = EOVERFLOW },
		{ .descriptor_error = ENODEV, .close_error = EOVERFLOW },
		{ .descriptor_mode_overridden = 1, .descriptor_mode = O_RDONLY,
		  .close_error = EOVERFLOW },
		{ .descriptor_mode_overridden = 1, .descriptor_mode = O_WRONLY,
		  .close_error = EOVERFLOW },
		{ .write_error = EIO, .close_error = EOVERFLOW },
		{ .sync_error = ENOSPC, .close_error = EOVERFLOW },
	};
	static const int expected_errno[] = {
		EPERM, EBUSY, EACCES, ESTALE, EIO, EAGAIN,
		ESTALE, ENODEV, EBADF, EBADF, EIO, ENOSPC,
	};
	static const int expected_status[] = {
		2, 2, 1, 2, 1, 1, 2, 2, 2, 2, 3, 3,
	};

	assert(sizeof(fixtures) / sizeof(fixtures[0]) ==
	       sizeof(expected_errno) / sizeof(expected_errno[0]));
	for (size_t index = 0; index < sizeof(fixtures) / sizeof(fixtures[0]);
	     ++index) {
		struct mock_format_context *context = &fixtures[index];
		struct format_runtime_ops ops = mock_ops(context);
		int status, observed_errno;

		test_diagnostic_errno_clobber = ECHILD;
		errno = 0;
		status = format_device_with_ops("/synthetic/card", &expected, &ops);
		observed_errno = errno;
		test_diagnostic_errno_clobber = 0;
		if (status != expected_status[index] ||
		    observed_errno != expected_errno[index] ||
		    context->write_calls != (index >= 10U ? 1U : 0U) ||
		    context->sync_calls != (index == 11U ? 1U : 0U) ||
		    context->close_calls != (index >= 3U ? 1U : 0U)) {
			fprintf(stderr, "FAIL: originating-errno case=%zu "
				"status=%d errno=%d expected=%d writes=%u syncs=%u\n",
				index, status, observed_errno, expected_errno[index],
				context->write_calls, context->sync_calls);
			abort();
		}
	}
}

static void test_publication_failures_are_explicitly_uncertain(void)
{
	struct format_expectation expected = authorized_expectation();
	struct mock_format_context write_context = { .write_error = EIO };
	struct format_runtime_ops write_ops = mock_ops(&write_context);
	struct mock_format_context sync_context = { .sync_error = EIO };
	struct format_runtime_ops sync_ops = mock_ops(&sync_context);
	struct mock_format_context close_context = { .close_error = EIO };
	struct format_runtime_ops close_ops = mock_ops(&close_context);

	assert(format_device_with_ops("/synthetic/card", &expected,
				      &write_ops) == 3);
	assert(write_context.write_calls == 1U);
	assert(write_context.sync_calls == 0U);
	/*
	 * The simulated failed write changed media, but it may coincidentally
	 * contain a structurally valid header because reserved tail bytes are zero.
	 * The error return still makes publication/durability uncertain.
	 */
	assert(!block_is_zero(write_context.media));
	assert(write_context.close_calls == 1U);

	assert(format_device_with_ops("/synthetic/card", &expected,
				      &sync_ops) == 3);
	assert(sync_context.write_calls == 1U);
	assert(sync_context.sync_calls == 1U);
	assert(swapz_sb_valid(sync_context.media, expected.device_bytes));
	assert(sync_context.close_calls == 1U);

	assert(format_device_with_ops("/synthetic/card", &expected,
				      &close_ops) == 3);
	assert(close_context.write_calls == 1U);
	assert(close_context.sync_calls == 1U);
	assert(swapz_sb_valid(close_context.media, expected.device_bytes));
	assert(close_context.close_calls == 1U);
}

static void test_zero_header_format_and_readback(void)
{
	struct format_expectation expected = authorized_expectation();
	struct mock_format_context context = {0};
	struct format_runtime_ops ops = mock_ops(&context);
	unsigned int i;

	assert(format_device_with_ops("/synthetic/card", &expected, &ops) == 0);
	assert(context.preopen_calls == 1U);
	assert(context.open_calls == 1U);
	assert(context.verify_calls == 4U);
	assert(context.authorization_calls == 5U);
	assert(context.read_calls == 2U);
	assert(context.random_calls == 1U);
	assert(context.write_calls == 1U);
	assert(context.sync_calls == 1U);
	assert(context.close_calls == 1U);
	assert(swapz_sb_valid(context.media, expected.device_bytes));
	assert((context.media[SWAPZ_SUPERBLOCK_UUID_OFFSET + 6U] & 0xf0U) ==
	       0x40U);
	assert((context.media[SWAPZ_SUPERBLOCK_UUID_OFFSET + 8U] & 0xc0U) ==
	       0x80U);
	for (i = SWAPZ_SUPERBLOCK_RESERVED_OFFSET;
	     i < SWAPZ_SUPERBLOCK_BYTES; ++i)
		assert(context.media[i] == 0U);
}

static void test_repeat_format_is_idempotent_and_non_destructive(void)
{
	struct format_expectation expected = authorized_expectation();
	struct mock_format_context context = {0};
	struct format_runtime_ops ops = mock_ops(&context);
	unsigned char original[SWAPZ_SUPERBLOCK_BYTES];

	make_valid_header(context.media, expected.device_bytes);
	memcpy(original, context.media, sizeof(original));
	assert(format_device_with_ops("/synthetic/card", &expected, &ops) == 0);
	assert(context.verify_calls == 2U);
	assert(context.authorization_calls == 3U);
	assert(context.read_calls == 1U);
	assert(context.random_calls == 0U);
	assert(context.write_calls == 0U);
	assert(context.sync_calls == 0U);
	assert(context.close_calls == 1U);
	assert(!memcmp(context.media, original, sizeof(original)));
}

static void test_disappearance_after_write_is_never_success(void)
{
	struct format_expectation expected = authorized_expectation();
	struct mock_format_context context = {
		.verify_errors = { 0, 0, ENODEV },
		.verify_error_count = 3U,
	};
	struct format_runtime_ops ops = mock_ops(&context);

	assert(format_device_with_ops("/synthetic/card", &expected, &ops) == 3);
	assert(context.write_calls == 1U);
	assert(context.sync_calls == 1U);
	assert(context.read_calls == 1U);
	assert(context.close_calls == 1U);
}

static void test_truncated_read_and_close_failure_are_not_success(void)
{
	struct format_expectation expected = authorized_expectation();
	struct mock_format_context read_context = { .read_error = EIO };
	struct format_runtime_ops read_ops = mock_ops(&read_context);
	struct mock_format_context close_context = { .close_error = EIO };
	struct format_runtime_ops close_ops = mock_ops(&close_context);
	unsigned char buffer[SWAPZ_SUPERBLOCK_BYTES];
	FILE *file = tmpfile();
	int fd;

	assert(format_device_with_ops("/synthetic/card", &expected,
				      &read_ops) == 1);
	assert(read_context.write_calls == 0U);
	assert(read_context.close_calls == 1U);

	assert(file != NULL);
	fd = fileno(file);
	assert(fd >= 0);
	assert(write(fd, "abc", 3U) == 3);
	errno = 0;
	assert(exact_io(fd, buffer, sizeof(buffer), 0) < 0);
	assert(errno == EIO);
	assert(fclose(file) == 0);

	make_valid_header(close_context.media, expected.device_bytes);
	assert(format_device_with_ops("/synthetic/card", &expected,
				      &close_ops) == 1);
	assert(close_context.write_calls == 0U);
	assert(close_context.close_calls == 1U);
}

int main(void)
{
	test_numeric_bound_parser();
	test_format_expectation_parser();
	test_identity_table_rejects_substitution();
	test_topology_flags_fail_closed();
	test_mountinfo_device_parser();
	test_mountinfo_adversarial_inventory();
	test_mount_and_swap_identity_conflicts();
	test_mounts_in_other_namespaces_refuse_formatting();
	test_swap_inventory_requires_complete_kernel_table();
	test_swap_adversarial_inventory();
	test_namespace_swap_ambiguity_never_writes();
	test_formatter_path_admission();
	test_superblock_validation_and_reserved_bytes();
	test_unbound_cli_is_blocked_before_io();
	test_protected_selector_is_mandatory();
	test_selector_revocation_before_write_refuses();
	test_partial_header_write_is_not_resumed();
	test_preopen_permission_refuses_before_open_or_write();
	test_wrong_opened_device_refuses_before_read_or_write();
	test_invalid_header_refuses_without_write();
	test_stale_identity_refuses_at_last_prewrite_gate();
	test_inventory_gate_errors_never_reach_header_write();
	test_device_disappearance_before_write_refuses();
	test_read_only_transition_before_write_refuses();
	test_formatter_originating_errno_survives_diagnostics_and_close();
	test_publication_failures_are_explicitly_uncertain();
	test_zero_header_format_and_readback();
	test_repeat_format_is_idempotent_and_non_destructive();
	test_disappearance_after_write_is_never_success();
	test_truncated_read_and_close_failure_are_not_success();
	test_real_cli_exclusive_open_permission_refuses_without_io();
	test_real_cli_descriptor_access_modes_refuse_without_write();
	test_real_cli_snapshots_refuse_before_first_header_write();
	test_real_cli_active_swap_inventory_never_writes();
	test_missing_partition_slaves_directory_is_empty();
	test_missing_partition_slaves_does_not_hide_removal();
	puts("PASS: swapzctl formatter identity and destructive-action gates");
	return 0;
}
