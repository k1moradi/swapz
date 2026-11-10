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
#define SEGMENT_PAGES 256U

static void put_u32_le(unsigned char *bytes, unsigned int value)
{
	bytes[0] = (unsigned char)value;
	bytes[1] = (unsigned char)(value >> 8);
	bytes[2] = (unsigned char)(value >> 16);
	bytes[3] = (unsigned char)(value >> 24);
}

static void put_u32_be(unsigned char *bytes, unsigned int value)
{
	bytes[0] = (unsigned char)(value >> 24);
	bytes[1] = (unsigned char)(value >> 16);
	bytes[2] = (unsigned char)(value >> 8);
	bytes[3] = (unsigned char)value;
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
	struct swapz_linux_swap_layout layout;
	const unsigned int full_last_page =
		(unsigned int)(DEVICE_BYTES / SWAPZ_SUPERBLOCK_BYTES - 1ULL);
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

	if (!swapz_linux_swap_header_parse(header, DEVICE_BYTES, &layout) ||
	    layout.last_page != full_last_page || layout.bad_pages ||
	    layout.byte_swapped) {
		fprintf(stderr, "FAIL: ordinary swap layout parser mismatch\n");
		++failures;
	}

	/* Linux accepts a v1 header whose integer fields need byte swapping. */
	build_linux_swap_header(header);
	put_u32_be(header + SWAPZ_LINUX_SWAP_VERSION_OFFSET, 1U);
	put_u32_be(header + SWAPZ_LINUX_SWAP_LAST_PAGE_OFFSET, full_last_page);
	put_u32_be(header + SWAPZ_LINUX_SWAP_BAD_PAGES_OFFSET, 0U);
	if (!swapz_linux_swap_header_valid(header, DEVICE_BYTES) ||
	    !swapz_linux_swap_header_parse(header, DEVICE_BYTES, &layout) ||
	    !layout.byte_swapped || layout.last_page != full_last_page) {
		fprintf(stderr, "FAIL: rejected byte-swapped ordinary Linux swap header\n");
		++failures;
	}

	/*
	 * The parser understands Linux layouts that swapz admission still treats
	 * conservatively until clean-segment remapping is wired end to end.
	 */
	build_linux_swap_header(header);
	put_u32_le(header + SWAPZ_LINUX_SWAP_LAST_PAGE_OFFSET,
		   full_last_page - SEGMENT_PAGES);
	if (!swapz_linux_swap_header_parse(header, DEVICE_BYTES, &layout) ||
	    layout.last_page != full_last_page - SEGMENT_PAGES ||
	    swapz_linux_swap_header_valid(header, DEVICE_BYTES)) {
		fprintf(stderr, "FAIL: smaller declared Linux swap area parsing\n");
		++failures;
	}

	build_linux_swap_header(header);
	put_u32_le(header + SWAPZ_LINUX_SWAP_BAD_PAGES_OFFSET, 1U);
	put_u32_le(header + SWAPZ_LINUX_SWAP_BAD_PAGE_LIST_OFFSET, 257U);
	if (!swapz_linux_swap_header_parse(header, DEVICE_BYTES, &layout) ||
	    layout.bad_pages != 1U ||
	    swapz_linux_swap_bad_page(header, &layout, 0U) != 257U ||
	    swapz_linux_swap_header_valid(header, DEVICE_BYTES)) {
		fprintf(stderr, "FAIL: Linux bad-page list parsing\n");
		++failures;
	}
	put_u32_le(header + SWAPZ_LINUX_SWAP_BAD_PAGES_OFFSET, 2U);
	put_u32_le(header + SWAPZ_LINUX_SWAP_BAD_PAGE_LIST_OFFSET +
		   sizeof(unsigned int), 257U);
	if (!swapz_linux_swap_header_parse(header, DEVICE_BYTES, &layout) ||
	    layout.bad_pages != 2U ||
	    swapz_linux_swap_bad_page(header, &layout, 1U) != 257U ||
	    swapz_linux_swap_header_valid(header, DEVICE_BYTES) ||
	    swapz_linux_swap_clean_segment_count(
		    header, &layout, SEGMENT_PAGES) !=
		    full_last_page / SEGMENT_PAGES - 1U) {
		fprintf(stderr,
			"FAIL: duplicate Linux bad-page entries changed clean segments\n");
		++failures;
	}

	/* A larger block device may carry an intentionally smaller declared
	 * SWAPSPACE2 area; the 32-bit header field limits the area, not the disk. */
	build_linux_swap_header(header);
	if (!swapz_linux_swap_header_parse(
		    header, DEVICE_BYTES + (16ULL * 1024ULL * 1024ULL * 1024ULL),
		    &layout) ||
	    layout.last_page != full_last_page) {
		fprintf(stderr, "FAIL: rejected bounded swap area on larger device\n");
		++failures;
	}

	/* Start the optional-UUID check with a conventional valid header. */
	build_linux_swap_header(header);
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
