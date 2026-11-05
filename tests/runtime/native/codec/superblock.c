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
	if (failures)
		fprintf(stderr, "FAIL: %d malformed SWZ headers were accepted\n", failures);
	if (failures)
		return 1;
	puts("PASS: exact SWZ header and malformed headers");
	return 0;
}
