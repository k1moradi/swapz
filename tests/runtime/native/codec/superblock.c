/* SPDX-License-Identifier: GPL-2.0-only */
/* Exercise the exact freestanding production SWZ authorization validator. */
#include "superblock.h"

#include <stdio.h>
#include <string.h>

#define DEVICE_BYTES (16ULL * 1024ULL * 1024ULL * 1024ULL)

static int check_invalid(const unsigned char *header, const char *reason)
{
	if (!swapz_sb_valid(header, DEVICE_BYTES))
		return 0;
	fprintf(stderr, "FAIL: accepted %s superblock\n", reason);
	return 1;
}

/* Normal Linux swap is already formatted; no SWZ header is necessary.
 * The raw block-zero image is retained verbatim and never written by this
 * validator. Data placement begins at the following 4096-byte page.
 */
static int check_linux_swap_header(void)
{
	unsigned char header[SWAPZ_SUPERBLOCK_BYTES] = { 0 };
	unsigned int index;
	int failures = 0;

	swapz_sb_put_u32(header + SWAPZ_LINUX_SWAP_VERSION_OFFSET, 1U);
	swapz_sb_put_u32(header + SWAPZ_LINUX_SWAP_LAST_PAGE_OFFSET,
			 (unsigned int)(DEVICE_BYTES / SWAPZ_SUPERBLOCK_BYTES - 1ULL));
	for (index = 0; index < SWAPZ_LINUX_SWAP_UUID_BYTES; ++index)
		header[SWAPZ_LINUX_SWAP_UUID_OFFSET + index] =
			(unsigned char)(index + 1U);
	memcpy(header + SWAPZ_SUPERBLOCK_BYTES - SWAPZ_LINUX_SWAP_MAGIC_BYTES,
	       "SWAPSPACE2", SWAPZ_LINUX_SWAP_MAGIC_BYTES);
	if (!swapz_linux_swap_header_valid(header, DEVICE_BYTES) ||
	    swapz_sb_valid(header, DEVICE_BYTES)) {
		fprintf(stderr, "FAIL: ordinary Linux swap header is not admitted independently\n");
		return 1;
	}
	if (swapz_linux_swap_header_valid(header, DEVICE_BYTES - 1U) ||
	    swapz_linux_swap_header_valid(header, SWAPZ_SUPERBLOCK_BYTES)) {
		fprintf(stderr, "FAIL: accepted invalid backing device geometry\n");
		++failures;
	}
	header[SWAPZ_SUPERBLOCK_BYTES - 1U] ^= 1U;
	failures += swapz_linux_swap_header_valid(header, DEVICE_BYTES);
	header[SWAPZ_SUPERBLOCK_BYTES - 1U] ^= 1U;
	swapz_sb_put_u32(header + SWAPZ_LINUX_SWAP_VERSION_OFFSET, 2U);
	failures += swapz_linux_swap_header_valid(header, DEVICE_BYTES);
	swapz_sb_put_u32(header + SWAPZ_LINUX_SWAP_VERSION_OFFSET, 1U);
	swapz_sb_put_u32(header + SWAPZ_LINUX_SWAP_LAST_PAGE_OFFSET,
			 (unsigned int)(DEVICE_BYTES / SWAPZ_SUPERBLOCK_BYTES));
	failures += swapz_linux_swap_header_valid(header, DEVICE_BYTES);
	swapz_sb_put_u32(header + SWAPZ_LINUX_SWAP_LAST_PAGE_OFFSET, 2U);
	swapz_sb_put_u32(header + SWAPZ_LINUX_SWAP_BAD_PAGES_OFFSET, 1U);
	failures += swapz_linux_swap_header_valid(header, DEVICE_BYTES);
	swapz_sb_put_u32(header + SWAPZ_LINUX_SWAP_BAD_PAGES_OFFSET, 0U);
	memset(header + SWAPZ_LINUX_SWAP_UUID_OFFSET, 0,
	       SWAPZ_LINUX_SWAP_UUID_BYTES);
	failures += swapz_linux_swap_header_valid(header, DEVICE_BYTES);
	if (failures)
		fprintf(stderr, "FAIL: %d malformed Linux swap headers were accepted\n", failures);
	return failures != 0;
}

int main(void)
{
	unsigned char header[SWAPZ_SUPERBLOCK_BYTES] = { 0 };
	unsigned int index;
	int failures = 0;

	memcpy(header + SWAPZ_SUPERBLOCK_MAGIC_OFFSET,
	       swapz_superblock_magic, SWAPZ_SUPERBLOCK_MAGIC_BYTES);
	swapz_sb_put_u32(header + SWAPZ_SUPERBLOCK_VERSION_OFFSET,
			 SWAPZ_SUPERBLOCK_VERSION);
	swapz_sb_put_u32(header + SWAPZ_SUPERBLOCK_HEADER_BYTES_OFFSET,
			 SWAPZ_SUPERBLOCK_BYTES);
	swapz_sb_put_u64(header + SWAPZ_SUPERBLOCK_DEVICE_BYTES_OFFSET,
			 DEVICE_BYTES);
	for (index = 0; index < SWAPZ_SUPERBLOCK_UUID_BYTES; ++index)
		header[SWAPZ_SUPERBLOCK_UUID_OFFSET + index] = (unsigned char)(index + 1U);
	if (!swapz_sb_valid(header, DEVICE_BYTES)) {
		fprintf(stderr, "FAIL: exact SWZ superblock rejected\n");
		return 1;
	}

	header[SWAPZ_SUPERBLOCK_MAGIC_OFFSET] ^= 1U;
	failures += check_invalid(header, "wrong-magic");
	header[SWAPZ_SUPERBLOCK_MAGIC_OFFSET] ^= 1U;

	/* The verified device geometry, not just header self-description, matters. */
	if (swapz_sb_valid(header, DEVICE_BYTES - SWAPZ_SUPERBLOCK_BYTES)) {
		fprintf(stderr, "FAIL: accepted mismatched device geometry\n");
		++failures;
	}
	swapz_sb_put_u64(header + SWAPZ_SUPERBLOCK_DEVICE_BYTES_OFFSET,
			 DEVICE_BYTES - SWAPZ_SUPERBLOCK_BYTES);
	failures += check_invalid(header, "header device size mismatch");
	swapz_sb_put_u64(header + SWAPZ_SUPERBLOCK_DEVICE_BYTES_OFFSET,
			 DEVICE_BYTES);

	swapz_sb_put_u32(header + SWAPZ_SUPERBLOCK_HEADER_BYTES_OFFSET,
			 SWAPZ_SUPERBLOCK_BYTES - 1U);
	failures += check_invalid(header, "header byte count mismatch");
	swapz_sb_put_u32(header + SWAPZ_SUPERBLOCK_HEADER_BYTES_OFFSET,
			 SWAPZ_SUPERBLOCK_BYTES);

	swapz_sb_put_u32(header + SWAPZ_SUPERBLOCK_VERSION_OFFSET,
			 SWAPZ_SUPERBLOCK_VERSION + 1U);
	failures += check_invalid(header, "wrong-version");
	swapz_sb_put_u32(header + SWAPZ_SUPERBLOCK_VERSION_OFFSET,
			 SWAPZ_SUPERBLOCK_VERSION);

	memset(header + SWAPZ_SUPERBLOCK_UUID_OFFSET, 0,
	       SWAPZ_SUPERBLOCK_UUID_BYTES);
	failures += check_invalid(header, "zero-uuid");
	header[SWAPZ_SUPERBLOCK_UUID_OFFSET] = 1U;

	/* Every byte outside the defined 40-byte prefix is reserved and zero. */
	for (index = SWAPZ_SUPERBLOCK_UUID_OFFSET + SWAPZ_SUPERBLOCK_UUID_BYTES;
	     index < SWAPZ_SUPERBLOCK_BYTES; ++index) {
		header[index] = 0x80U;
		if (swapz_sb_valid(header, DEVICE_BYTES))
			++failures;
		header[index] = 0;
	}
	failures += check_linux_swap_header();
	if (failures)
		fprintf(stderr, "FAIL: %d malformed backing headers were accepted\n", failures);
	if (failures)
		return 1;
	puts("PASS: unchanged Linux swap backing and synthetic SWZ header validators");
	return 0;
}
