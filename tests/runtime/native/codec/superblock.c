/* SPDX-License-Identifier: GPL-2.0-only */
/*
 * Exercise the only physical backing-header contract: an existing ordinary
 * SWAPSPACE2 partition. Validation is read-only and must not depend on a
 * swapz-specific on-media identity.
 */
#include "superblock.h"

#include <stdio.h>
#include <string.h>

#define DEVICE_BYTES (16ULL * 1024ULL * 1024ULL * 1024ULL)

static void put_u32_le(unsigned char *bytes, unsigned int value)
{
	bytes[0] = (unsigned char)value;
	bytes[1] = (unsigned char)(value >> 8);
	bytes[2] = (unsigned char)(value >> 16);
	bytes[3] = (unsigned char)(value >> 24);
}

static void build_linux_swap_header(unsigned char header[SWAPZ_SUPERBLOCK_BYTES])
{
	unsigned int index;

	memset(header, 0, SWAPZ_SUPERBLOCK_BYTES);
	put_u32_le(header + SWAPZ_LINUX_SWAP_VERSION_OFFSET, 1U);
	put_u32_le(
		header + SWAPZ_LINUX_SWAP_LAST_PAGE_OFFSET,
		(unsigned int)(DEVICE_BYTES / SWAPZ_SUPERBLOCK_BYTES - 1ULL));
	put_u32_le(header + SWAPZ_LINUX_SWAP_BAD_PAGES_OFFSET, 0U);
	for (index = 0; index < SWAPZ_LINUX_SWAP_UUID_BYTES; ++index)
		header[SWAPZ_LINUX_SWAP_UUID_OFFSET + index] =
			(unsigned char)(index + 1U);
	memcpy(
		header + SWAPZ_SUPERBLOCK_BYTES - SWAPZ_LINUX_SWAP_MAGIC_BYTES,
		"SWAPSPACE2", SWAPZ_LINUX_SWAP_MAGIC_BYTES);
}

int main(void)
{
	unsigned char header[SWAPZ_SUPERBLOCK_BYTES];
	unsigned char original[SWAPZ_SUPERBLOCK_BYTES];
	int failures = 0;

	build_linux_swap_header(header);
	memcpy(original, header, sizeof(original));
	if (!swapz_linux_swap_header_valid(header, DEVICE_BYTES)) {
		fprintf(stderr, "FAIL: rejected valid ordinary Linux swap header\n");
		++failures;
	}
	if (memcmp(header, original, sizeof(header))) {
		fprintf(stderr, "FAIL: read-only swap-header validation modified bytes\n");
		++failures;
	}

	/* Linux swap UUID is optional; PARTUUID and exact geometry bind backing. */
	memset(header + SWAPZ_LINUX_SWAP_UUID_OFFSET, 0,
	       SWAPZ_LINUX_SWAP_UUID_BYTES);
	if (!swapz_linux_swap_header_valid(header, DEVICE_BYTES)) {
		fprintf(stderr, "FAIL: rejected valid Linux swap with cleared UUID\n");
		++failures;
	}

	build_linux_swap_header(header);
	put_u32_le(header + SWAPZ_LINUX_SWAP_VERSION_OFFSET, 2U);
	if (swapz_linux_swap_header_valid(header, DEVICE_BYTES))
		++failures;

	build_linux_swap_header(header);
	put_u32_le(header + SWAPZ_LINUX_SWAP_BAD_PAGES_OFFSET, 1U);
	if (swapz_linux_swap_header_valid(header, DEVICE_BYTES))
		++failures;

	build_linux_swap_header(header);
	put_u32_le(
		header + SWAPZ_LINUX_SWAP_LAST_PAGE_OFFSET,
		(unsigned int)(DEVICE_BYTES / SWAPZ_SUPERBLOCK_BYTES - 2ULL));
	if (swapz_linux_swap_header_valid(header, DEVICE_BYTES))
		++failures;

	build_linux_swap_header(header);
	header[SWAPZ_SUPERBLOCK_BYTES - 1U] ^= 1U;
	if (swapz_linux_swap_header_valid(header, DEVICE_BYTES))
		++failures;

	build_linux_swap_header(header);
	if (swapz_linux_swap_header_valid(header, DEVICE_BYTES - 1U) ||
	    swapz_linux_swap_header_valid(
		    header, DEVICE_BYTES + SWAPZ_SUPERBLOCK_BYTES) ||
	    swapz_linux_swap_header_valid(
		    header, 2ULL * SWAPZ_SUPERBLOCK_BYTES) ||
	    swapz_linux_swap_header_valid(NULL, DEVICE_BYTES))
		++failures;

	if (failures) {
		fprintf(stderr,
			"FAIL: %d malformed/nonmatching Linux swap headers were admitted\n",
			failures);
		return 1;
	}
	puts("PASS: ordinary SWAPSPACE2 validation is read-only and exact-geometry");
	return 0;
}
