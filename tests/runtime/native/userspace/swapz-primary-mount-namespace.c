// SPDX-License-Identifier: GPL-2.0-only
#define _GNU_SOURCE
#include <assert.h>
#include <dirent.h>
#include <errno.h>
#include <fcntl.h>
#include <ftw.h>
#include <limits.h>
#include <stdint.h>
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/sysmacros.h>
#include <unistd.h>

/*
 * Compile the actual production manager, without SWAPZ_PRIMARY_ROOTLESS_TEST:
 * that macro intentionally disables the production mount reader. Redirect only
 * procfs input to owned regular files; never create a mount, open a block
 * device, or invoke a lifecycle/mutation command.
 */
static char fixture_proc_root[PATH_MAX];
static int fixture_mount_open_error;
static int fixture_inventory_error;
static int fixture_namespace_stat_error;
static int fixture_mount_read_error;
static int fixture_mount_fd = -1;
static unsigned int fixture_destructive_calls;

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

static int fixture_other_mountinfo(const char *path)
{
	const char *suffix = "3031/mountinfo";
	size_t length = strlen(path);
	size_t suffix_length = strlen(suffix);

	return length >= suffix_length &&
	       !strcmp(path + length - suffix_length, suffix) &&
	       (length == suffix_length || path[length - suffix_length - 1U] == '/');
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
	if (fixture_other_mountinfo(path) && fixture_mount_open_error) {
		errno = fixture_mount_open_error;
		return -1;
	}
	fd = open(fixture_path(path, converted), flags, mode);
	if (fd >= 0 && fixture_other_mountinfo(path))
		fixture_mount_fd = fd;
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
	if (fixture_other_mountinfo(path) && fixture_mount_open_error) {
		errno = fixture_mount_open_error;
		return -1;
	}
	fd = openat(directory_fd, fixture_path(path, converted), flags, mode);
	if (fd >= 0 && fixture_other_mountinfo(path))
		fixture_mount_fd = fd;
	return fd;
}

static ssize_t fixture_read(int fd, void *buffer, size_t length)
{
	if (fd == fixture_mount_fd && fixture_mount_read_error) {
		errno = fixture_mount_read_error;
		return -1;
	}
	return read(fd, buffer, length);
}

static FILE *fixture_fopen(const char *path, const char *mode)
	__attribute__((unused));
static FILE *fixture_fopen(const char *path, const char *mode)
{
	char converted[PATH_MAX];

	if (fixture_other_mountinfo(path) && fixture_mount_open_error) {
		errno = fixture_mount_open_error;
		return NULL;
	}
	return fopen(fixture_path(path, converted), mode);
}

static DIR *fixture_opendir(const char *path)
{
	char converted[PATH_MAX];

	if (!strcmp(path, "/proc") && fixture_inventory_error) {
		errno = fixture_inventory_error;
		return NULL;
	}
	return opendir(fixture_path(path, converted));
}

static int fixture_stat(const char *path, struct stat *info)
	__attribute__((unused));
static int fixture_stat(const char *path, struct stat *info)
{
	char converted[PATH_MAX];

	if (strstr(path, "/3031/ns/mnt") && fixture_namespace_stat_error) {
		errno = fixture_namespace_stat_error;
		return -1;
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

/* A destructive write during an inventory test is always a test failure. */
static ssize_t fixture_pwrite(int fd, const void *buffer, size_t length,
			      off_t offset)
	__attribute__((unused));
static ssize_t fixture_pwrite(int fd, const void *buffer, size_t length,
			      off_t offset)
{
	(void)fd;
	(void)buffer;
	(void)length;
	(void)offset;
	++fixture_destructive_calls;
	errno = EPERM;
	return -1;
}

#define open(...) fixture_open(__VA_ARGS__)
#define openat(...) fixture_openat(__VA_ARGS__)
#define read(...) fixture_read(__VA_ARGS__)
#define fopen(...) fixture_fopen(__VA_ARGS__)
#define opendir(...) fixture_opendir(__VA_ARGS__)
#define stat(...) fixture_stat(__VA_ARGS__)
#define lstat(...) fixture_lstat(__VA_ARGS__)
#define pwrite(...) fixture_pwrite(__VA_ARGS__)
#define main swapz_primary_program_main
#include "../../../../src/userspace/swapz-primary.c"
#undef main
#undef pwrite
#undef lstat
#undef stat
#undef opendir
#undef fopen
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

static void fixture_unlink(const char *relative)
{
	char path[PATH_MAX];
	int length = snprintf(path, sizeof(path), "%s/%s", fixture_proc_root,
			      relative);

	assert(length > 0 && (size_t)length < sizeof(path));
	assert(unlink(path) == 0);
}

static void fixture_reset(void)
{
	fixture_mount_open_error = 0;
	fixture_inventory_error = 0;
	fixture_namespace_stat_error = 0;
	fixture_mount_read_error = 0;
	fixture_mount_fd = -1;
	fixture_file("self/mountinfo",
		     "36 25 259:0 / / rw - ext4 /dev/root rw\n");
	fixture_file("3031/mountinfo",
		     "36 25 259:9 / / rw - ext4 /dev/other-root rw\n");
	fixture_file("3031/ns/mnt", "mount namespace still present\n");
}

static unsigned int fixture_failures;

static void expect_mount_admission(const char *case_name, int should_allow)
{
	struct swapz_primary_mount_facts facts = {0};
	int result;
	int allowed;

	errno = 0;
	result = swapz_primary_read_mount_facts(&facts);
	allowed = result == 0 && !facts.target_mounted;
	if (allowed != should_allow ||
	    (allowed && (!facts.root_mount_seen ||
			 facts.root_device != makedev(259U, 0U)))) {
		fprintf(stderr, "FAIL: %s: result=%d errno=%d target=%d "
			"root_seen=%d root=%u:%u (expected %s)\n",
			case_name, result, errno, facts.target_mounted,
			facts.root_mount_seen, major(facts.root_device),
			minor(facts.root_device),
			should_allow ? "admitted" : "refused");
		++fixture_failures;
	}
	if (fixture_destructive_calls) {
		fprintf(stderr, "FAIL: inventory attempted destructive write\n");
		++fixture_failures;
	}
}

static int fixture_remove_entry(const char *path, const struct stat *info,
				int type, struct FTW *tree)
{
	(void)info;
	(void)type;
	(void)tree;
	return remove(path);
}

static void test_independent_admission_gates(void)
{
	struct swapz_primary_swap_entry entries[2] = {0};
	dev_t devices[2] = {0};
	unsigned char is_block[2] = {0};
	char holder_path[PATH_MAX];
	int length;

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
	assert(snprintf(path, sizeof(path), "%s/3031", fixture_proc_root) > 0);
	assert(mkdir(path, 0700) == 0);
	assert(snprintf(path, sizeof(path), "%s/3031/ns", fixture_proc_root) > 0);
	assert(mkdir(path, 0700) == 0);
	swapz_primary_selected_target.device_major = 8U;
	swapz_primary_selected_target.device_minor = 1U;
	fixture_reset();
	expect_mount_admission("only local root mount", 1);
	fixture_file("3031/mountinfo",
		     "36 25 259:9 / / rw - ext4 /dev/other-root rw\n"
		     "37 36 8:2 / /other rw - ext4 /dev/sda2 rw\n");
	expect_mount_admission("unrelated sibling", 1);
	fixture_file("3031/mountinfo",
		     "36 25 259:9 / / rw - ext4 /dev/other-root rw\n"
		     "37 36 8:1 / /selected rw - ext4 /dev/sda1 rw\n");
	expect_mount_admission("selected partition in another namespace", 0);
	fixture_file("3031/mountinfo",
		     "36 25 259:9 / / rw - ext4 /dev/other-root rw\n"
		     "37 36 8:0 / /parent rw - ext4 /dev/sda rw\n");
	expect_mount_admission("selected parent in another namespace", 0);

	fixture_reset();
	fixture_file("self/mountinfo", "malformed\n");
	expect_mount_admission("malformed local mount table", 0);
	fixture_reset();
	fixture_unlink("self/mountinfo");
	expect_mount_admission("missing local mount table", 0);
	fixture_reset();
	fixture_file("3031/mountinfo", "malformed\n");
	expect_mount_admission("malformed remote mount table", 0);
	fixture_reset();
	fixture_mount_read_error = EIO;
	expect_mount_admission("opened remote table read error", 0);
	fixture_reset();
	fixture_inventory_error = EACCES;
	expect_mount_admission("permission-denied PID inventory", 0);
	fixture_reset();
	fixture_mount_open_error = EACCES;
	expect_mount_admission("permission-denied remote table", 0);
	fixture_reset();
	fixture_unlink("3031/mountinfo");
	expect_mount_admission("missing table with live namespace", 0);

	for (index = 0; index < sizeof(exit_errors) / sizeof(exit_errors[0]); ++index) {
		fixture_reset();
		fixture_mount_open_error = exit_errors[index];
		expect_mount_admission("exit errno with live namespace", 0);
		fixture_unlink("3031/ns/mnt");
		expect_mount_admission("exit errno with absent namespace", 1);
	}
	fixture_reset();
	fixture_mount_open_error = EINVAL;
	fixture_namespace_stat_error = EACCES;
	expect_mount_admission("uninspectable namespace is not process exit", 0);
	fixture_reset();
	fixture_unlink("3031/mountinfo");
	fixture_unlink("3031/ns/mnt");
	expect_mount_admission("missing table and vanished namespace", 1);
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
