// SPDX-License-Identifier: GPL-2.0-only
/* Read-only V3 administrative tool; V3 is experimental and null_blk-only. */
#include <stdio.h>
#include <string.h>
#include <sys/stat.h>

#ifndef SWAPZ_VERSION
#define SWAPZ_VERSION "unknown"
#endif

static void usage(FILE *out)
{
	fputs("Usage: swapz3ctl version | status | help\n", out);
	fputs("EXPERIMENTAL V3: device activation is not supported.\n", out);
}

int main(int argc, char **argv)
{
	struct stat info;

	if (argc != 2) {
		usage(stderr);
		return 2;
	}
	if (!strcmp(argv[1], "help") || !strcmp(argv[1], "--help")) {
		usage(stdout);
		return 0;
	}
	if (!strcmp(argv[1], "version") || !strcmp(argv[1], "--version")) {
		printf("swapz3ctl %s (EXPERIMENTAL, null_blk-only)\n",
		       SWAPZ_VERSION);
		return 0;
	}
	if (!strcmp(argv[1], "status")) {
		if (stat("/sys/module/dm_swapz", &info) == 0 &&
		    S_ISDIR(info.st_mode))
			puts("dm-swapz: loaded (experimental)");
		else
			puts("dm-swapz: not loaded (experimental)");
		return 0;
	}
	usage(stderr);
	fputs("BLOCKED: no activation or swap changes permitted.\n", stderr);
	return 2;
}
