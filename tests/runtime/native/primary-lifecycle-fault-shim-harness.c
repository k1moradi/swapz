// SPDX-License-Identifier: GPL-2.0-only
#if defined(SWAPZ_PRIMARY_PACKAGE_ADMISSION_FIXTURE)
/*
 * Rootless linker fixture for source-extracted production primary admission.
 * The real dispatcher and package guard run in the other translation unit.
 * These stand-ins observe but NEVER perform header/device/kernel mutations.
 */
#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <limits.h>
#include <linux/stat.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/syscall.h>
#include <sys/types.h>
#include <unistd.h>

int swapz_primary_command(int argc, char **argv);

static unsigned int prepared_headers;
static unsigned int mapper_changes;
static unsigned int mkswap_calls;
static unsigned int swapon_calls;
static unsigned int prepare_calls;
static unsigned int start_calls;
static unsigned int stop_calls;
static unsigned int recover_calls;

int swapz_primary_privileged_execution_enabled(void)
{
	return 1;
}

int swapz_primary_cleanup_execution_enabled(void)
{
	return 1;
}

int swapz_primary_prepare_metadata(void)
{
	++prepare_calls;
	++prepared_headers;
	++mapper_changes;
	return 0;
}

int swapz_primary_start_prepared(void)
{
	++start_calls;
	++mapper_changes;
	++mkswap_calls;
	++swapon_calls;
	return 0;
}

int swapz_primary_stop_active(void)
{
	++stop_calls;
	return 0;
}

int swapz_primary_recover(void)
{
	++recover_calls;
	return 0;
}

int swapz_primary_read_only_plan(void)
{
	return 0;
}

int swapz_primary_target_config_read(char *partuuid)
{
	(void)partuuid;
	errno = EPERM;
	return -1;
}

int swapz_primary_systemd_target_units(const char *partuuid,
	char *device_unit, char *swap_unit)
{
	(void)partuuid;
	(void)device_unit;
	(void)swap_unit;
	errno = EPERM;
	return -1;
}

int swapz_primary_qualification_import_serialized(const char *report_path)
{
	(void)report_path;
	errno = EPERM;
	return -1;
}

/*
 * Inject a mount-ID disagreement in statx metadata only; never mount or
 * bind-mount anything. The production guard still checks both identities.
 */
int statx(int directory_fd, const char *pathname, int flags,
	unsigned int mask, struct statx *metadata)
{
	const char *change_mount = getenv("SWAPZ_TEST_CHANGED_MOUNT_ID");
	int result = (int)syscall(SYS_statx, directory_fd, pathname, flags,
		mask, metadata);

	if (result == 0 && change_mount && !strcmp(change_mount, "1") &&
	    (flags & AT_SYMLINK_NOFOLLOW) != 0 &&
	    !strcmp(pathname, "transactions") &&
	    (metadata->stx_mask & STATX_MNT_ID) != 0)
		++metadata->stx_mnt_id;
	return result;
}

/* Fake a different owner for just the open transaction directory. */
int fstat(int descriptor, struct stat *metadata)
{
	const char *wrong_owner = getenv("SWAPZ_TEST_WRONG_TRANSACTION_OWNER");
	const char *transactions = getenv("SWAPZ_TEST_PACKAGE_TRANSACTIONS");
	int result = (int)syscall(SYS_fstat, descriptor, metadata);

	if (result == 0 && wrong_owner && !strcmp(wrong_owner, "1") &&
	    transactions && *transactions) {
		char descriptor_path[64];
		char resolved_path[PATH_MAX];
		int path_length = snprintf(descriptor_path, sizeof(descriptor_path),
			"/proc/self/fd/%d", descriptor);
		ssize_t resolved_length;

		if (path_length < 0 || (size_t)path_length >=
		    sizeof(descriptor_path))
			abort();
		resolved_length = readlink(descriptor_path, resolved_path,
			sizeof(resolved_path) - 1U);
		if (resolved_length >= 0) {
			resolved_path[resolved_length] = '\0';
			if (!strcmp(resolved_path, transactions))
				metadata->st_uid = metadata->st_uid == 0 ? 1 : 0;
		}
	}
	return result;
}

int main(int argc, char **argv)
{
	int command_result;

	if (argc != 2)
		return 3;
	command_result = swapz_primary_command(1, &argv[1]);
	if (printf("SIMULATION prepare=%u start=%u stop=%u recover=%u "
		   "header=%u mapper=%u mkswap=%u swapon=%u\n",
		   prepare_calls, start_calls, stop_calls, recover_calls,
		   prepared_headers, mapper_changes, mkswap_calls,
		   swapon_calls) < 0 || fflush(stdout) == EOF)
		return 3;
	return command_result;
}

#else /* Original native fault-injection shim */
// SPDX-License-Identifier: GPL-2.0-only
#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/syscall.h>
#include <sys/types.h>
#include <unistd.h>

/*
 * Rootless fake kernel for the private linker-wrap fixture. No real swapon,
 * swapoff, module load, inventory read, or fsync is performed by this binary.
 * Its process-local fake inventory proves whether each fault did or did not
 * apply the simulated syscall before the wrapper returned ambiguity.
 */
long __wrap_syscall(long number, ...);
int __wrap_open(const char *path, int flags, ...);
int __wrap_fsync(int fd);

static int swap_is_active;
static int swap_syscall_calls;
static int normal_open_calls;
static int normal_fsync_calls;
static int module_syscall_calls;

long syscall(long number, ...)
{
	va_list arguments;

	va_start(arguments, number);
	if (number == SYS_swapon) {
		const char *path = va_arg(arguments, const char *);
		int flags = va_arg(arguments, int);

		if (strcmp(path, "/test/owned-mapper") || flags != 0)
			abort();
		swap_is_active = 1;
		++swap_syscall_calls;
	} else if (number == SYS_swapoff) {
		const char *path = va_arg(arguments, const char *);

		if (strcmp(path, "/test/owned-mapper"))
			abort();
		swap_is_active = 0;
		++swap_syscall_calls;
	} else if (number == SYS_finit_module) {
		int module_fd = va_arg(arguments, int);
		const char *parameters = va_arg(arguments, const char *);
		int flags = va_arg(arguments, int);

		if (module_fd != 23 || strcmp(parameters, "") || flags != 0)
			abort();
		++module_syscall_calls;
	} else if (number == SYS_delete_module) {
		const char *name = va_arg(arguments, const char *);
		int flags = va_arg(arguments, int);

		if (strcmp(name, "dm_swapz") || flags != O_NONBLOCK)
			abort();
		++module_syscall_calls;
	} else {
		abort();
	}
	va_end(arguments);
	return 0;
}

int open(const char *path, int flags, ...)
{
	if (strcmp(path, "/proc/swaps") || flags != O_RDONLY)
		abort();
	++normal_open_calls;
	return 47;
}

int fsync(int fd)
{
	if (fd < 0)
		abort();
	++normal_fsync_calls;
	return 0;
}

static void require_condition(int condition)
{
	if (!condition)
		abort();
}

int main(int argc, char **argv)
{
	const char *case_name;
	int stopping;
	long syscall_result;

	if (argc != 2)
		return 2;
	case_name = argv[1];
	if (strcmp(case_name, "passthrough"))
		require_condition(
			setenv("SWAPZ_PRIMARY_TEST_FAULT", case_name, 1) == 0);
	if (!strcmp(case_name, "state-dir-fsync")) {
		int directory_fd = openat(
			AT_FDCWD, ".", O_RDONLY | O_DIRECTORY | O_CLOEXEC);
		int regular_fd = openat(
			AT_FDCWD, "/dev/null", O_RDONLY | O_CLOEXEC);

		require_condition(directory_fd >= 0 && regular_fd >= 0);
		require_condition(setenv(
			"SWAPZ_PRIMARY_TEST_FSYNC_FAIL_DIRECTORY_CALL", "2", 1) == 0);
		/* First directory durability sync forwards. An intervening regular
		 * file sync must not advance the selected directory boundary. */
		require_condition(__wrap_fsync(directory_fd) == 0);
		require_condition(__wrap_fsync(regular_fd) == 0);
		errno = 0;
		require_condition(
			__wrap_fsync(directory_fd) == -1 && errno == EIO);
		require_condition(normal_fsync_calls == 2);
		require_condition(close(regular_fd) == 0);
		require_condition(close(directory_fd) == 0);
		return 0;
	}
	if (!strcmp(case_name, "passthrough")) {
		require_condition(
			__wrap_syscall(SYS_finit_module, 23, "", 0) == 0);
		require_condition(
			__wrap_syscall(SYS_swapon, "/test/owned-mapper", 0) == 0);
		require_condition(__wrap_open("/proc/swaps", O_RDONLY) == 47);
		require_condition(
			__wrap_syscall(SYS_swapoff, "/test/owned-mapper") == 0);
		require_condition(__wrap_syscall(
			SYS_delete_module, "dm_swapz", O_NONBLOCK) == 0);
		require_condition(__wrap_fsync(25) == 0);
		require_condition(!swap_is_active && swap_syscall_calls == 2);
		require_condition(module_syscall_calls == 2 &&
				  normal_fsync_calls == 1 && normal_open_calls == 1);
		return 0;
	}
	stopping = !strncmp(case_name, "swapoff-", 8) ||
		   !strncmp(case_name, "post-swapoff-", 13);
	swap_is_active = stopping;
	errno = 0;
	syscall_result = stopping ?
		__wrap_syscall(SYS_swapoff, "/test/owned-mapper") :
		__wrap_syscall(SYS_swapon, "/test/owned-mapper", 0);
	if (!strcmp(case_name, "swapon-eintr-applied") ||
	    !strcmp(case_name, "swapoff-eintr-applied")) {
		require_condition(syscall_result == -1 && errno == EINTR &&
				  swap_syscall_calls == 1);
		require_condition(swap_is_active == !stopping);
	} else if (!strcmp(case_name, "swapon-eintr-noeffect") ||
		   !strcmp(case_name, "swapon-eio-noeffect") ||
		   !strcmp(case_name, "swapoff-eintr-noeffect") ||
		   !strcmp(case_name, "swapoff-eio-noeffect") ||
		   !strcmp(case_name, "swapoff-ebusy-noeffect")) {
		int expected_errno = EINTR;

		if (!strcmp(case_name, "swapoff-ebusy-noeffect"))
			expected_errno = EBUSY;
		else if (!strcmp(case_name, "swapon-eio-noeffect") ||
			 !strcmp(case_name, "swapoff-eio-noeffect"))
			expected_errno = EIO;

		require_condition(syscall_result == -1 &&
				  errno == expected_errno &&
				  swap_syscall_calls == 0);
		require_condition(swap_is_active == stopping);
	} else if (!strcmp(case_name, "post-swapon-inventory-eio") ||
		   !strcmp(case_name, "post-swapoff-inventory-eio")) {
		require_condition(syscall_result == 0 &&
				  swap_syscall_calls == 1 &&
				  swap_is_active == !stopping);
		errno = 0;
		require_condition(__wrap_open("/proc/swaps", O_RDONLY) == -1 &&
				  errno == EIO);
		require_condition(__wrap_open("/proc/swaps", O_RDONLY) == 47 &&
				  normal_open_calls == 1);
	} else {
		return 2;
	}
	return 0;
}

#endif /* SWAPZ_PRIMARY_PACKAGE_ADMISSION_FIXTURE */
