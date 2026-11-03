// SPDX-License-Identifier: GPL-2.0-only
#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <stdarg.h>
#include <stdlib.h>
#include <string.h>
#include <sys/syscall.h>
#include <sys/types.h>

/*
 * Test-only linker-wrap boundary for the private owned-null_blk coordinator.
 * The coordinator is single-threaded; these counters are intentionally
 * process-local and non-atomic. With no SWAPZ_PRIMARY_TEST_* fault selected,
 * every supported production syscall/open/fsync call is forwarded unchanged.
 */
long __real_syscall(long number, ...);
int __real_open(const char *path, int flags, ...);
int __real_fsync(int fd);

static long last_swap_syscall;
static unsigned long fsync_calls;

static int fault_is(const char *name)
{
	const char *fault = getenv("SWAPZ_PRIMARY_TEST_FAULT");

	return fault && name && !strcmp(fault, name);
}

static int fsync_should_fail(void)
{
	const char *requested = getenv("SWAPZ_PRIMARY_TEST_FSYNC_FAIL_CALL");
	char *end = NULL;
	unsigned long call;

	++fsync_calls;
	if (!requested || !*requested)
		return 0;
	errno = 0;
	call = strtoul(requested, &end, 10);
	if (errno || end == requested || *end || !call)
		return 0;
	return call == fsync_calls;
}

long __wrap_syscall(long number, ...)
{
	va_list arguments;
	long result;

	va_start(arguments, number);
	switch (number) {
	case SYS_finit_module: {
		int module_fd = va_arg(arguments, int);
		const char *parameters = va_arg(arguments, const char *);
		int flags = va_arg(arguments, int);

		va_end(arguments);
		return __real_syscall(number, module_fd, parameters, flags);
	}
	case SYS_swapon: {
		const char *path = va_arg(arguments, const char *);
		int flags = va_arg(arguments, int);

		va_end(arguments);
		last_swap_syscall = SYS_swapon;
		if (fault_is("swapon-eintr-noeffect")) {
			errno = EINTR;
			return -1;
		}
		result = __real_syscall(number, path, flags);
		if (result == 0 && fault_is("swapon-eintr-applied")) {
			errno = EINTR;
			return -1;
		}
		return result;
	}
	case SYS_swapoff: {
		const char *path = va_arg(arguments, const char *);

		va_end(arguments);
		last_swap_syscall = SYS_swapoff;
		if (fault_is("swapoff-ebusy-noeffect")) {
			errno = EBUSY;
			return -1;
		}
		if (fault_is("swapoff-eintr-noeffect")) {
			errno = EINTR;
			return -1;
		}
		result = __real_syscall(number, path);
		if (result == 0 && fault_is("swapoff-eintr-applied")) {
			errno = EINTR;
			return -1;
		}
		return result;
	}
	case SYS_delete_module: {
		const char *name = va_arg(arguments, const char *);
		int flags = va_arg(arguments, int);

		va_end(arguments);
		return __real_syscall(number, name, flags);
	}
	default:
		va_end(arguments);
		errno = ENOSYS;
		return -1;
	}
}

int __wrap_open(const char *path, int flags, ...)
{
	mode_t mode = 0;
	int has_mode = (flags & O_CREAT) != 0;
	va_list arguments;

#ifdef O_TMPFILE
	has_mode = has_mode || ((flags & O_TMPFILE) == O_TMPFILE);
#endif
	if (has_mode) {
		va_start(arguments, flags);
		mode = va_arg(arguments, mode_t);
		va_end(arguments);
	}
	if (path && !strcmp(path, "/proc/swaps")) {
		if (last_swap_syscall == SYS_swapon &&
		    fault_is("post-swapon-inventory-eio")) {
			last_swap_syscall = 0;
			errno = EIO;
			return -1;
		}
		if (last_swap_syscall == SYS_swapoff &&
		    fault_is("post-swapoff-inventory-eio")) {
			last_swap_syscall = 0;
			errno = EIO;
			return -1;
		}
	}
	return has_mode ? __real_open(path, flags, mode) :
		__real_open(path, flags);
}

int __wrap_fsync(int fd)
{
	if (fsync_should_fail()) {
		errno = EIO;
		return -1;
	}
	return __real_fsync(fd);
}
