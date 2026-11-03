// SPDX-License-Identifier: GPL-2.0-only
#define main swapzctl_program_main
#include "../../../../src/userspace/swapz-primary.c"
#undef main

#include <assert.h>
#include <stdint.h>
#include <stdio.h>

int main(void)
{
	uint64_t pages = swapz_primary_maximum_logical_pages(
		SWAPZ_PRIMARY_PHYSICAL_BLOCKS);
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
	assert(swapz_primary_command(1, plan) == 2);
	assert(swapz_primary_command(1, prepare) == 2);
	assert(swapz_primary_command(1, start) == 2);
	assert(swapz_primary_command(1, stop) == 2);
	assert(swapz_primary_command(1, recover) == 2);
	puts("PASS: primary swap capacity boundary and disabled lifecycle gate");
	return 0;
}
