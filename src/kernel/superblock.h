/* SPDX-License-Identifier: GPL-2.0-only */
#ifndef SWAPZ_SUPERBLOCK_H
#define SWAPZ_SUPERBLOCK_H

/*
 * Physical backing is an existing ordinary Linux SWAPSPACE2 partition.
 * The first 4096-byte page remains byte-for-byte owned by Linux swap and is
 * never a swapz metadata area. swapz allocates only from the following page.
 */
#define SWAPZ_SUPERBLOCK_BYTES 4096U
#define SWAPZ_LINUX_SWAP_MAGIC_BYTES 10U
#define SWAPZ_LINUX_SWAP_VERSION_OFFSET 1024U
#define SWAPZ_LINUX_SWAP_LAST_PAGE_OFFSET 1028U
#define SWAPZ_LINUX_SWAP_BAD_PAGES_OFFSET 1032U
#define SWAPZ_LINUX_SWAP_UUID_OFFSET 1036U
#define SWAPZ_LINUX_SWAP_UUID_BYTES 16U

static inline unsigned int swapz_sb_get_u32(const unsigned char *bytes)
{
	return (unsigned int)bytes[0] |
	       ((unsigned int)bytes[1] << 8) |
	       ((unsigned int)bytes[2] << 16) |
	       ((unsigned int)bytes[3] << 24);
}

static inline int swapz_linux_swap_header_valid(
	const unsigned char *block, unsigned long long device_bytes)
{
	static const unsigned char magic[SWAPZ_LINUX_SWAP_MAGIC_BYTES] = {
		'S', 'W', 'A', 'P', 'S', 'P', 'A', 'C', 'E', '2'
	};
	const unsigned long long pages =
		device_bytes / SWAPZ_SUPERBLOCK_BYTES;
	unsigned int last_page;
	unsigned int index;

	if (!block || device_bytes % SWAPZ_SUPERBLOCK_BYTES ||
	    pages < 3U || pages > 0xffffffffULL ||
	    swapz_sb_get_u32(block + SWAPZ_LINUX_SWAP_VERSION_OFFSET) != 1U ||
	    swapz_sb_get_u32(block + SWAPZ_LINUX_SWAP_BAD_PAGES_OFFSET) != 0U)
		return 0;

	last_page = swapz_sb_get_u32(
		block + SWAPZ_LINUX_SWAP_LAST_PAGE_OFFSET);
	/*
	 * The partition geometry and Linux swap header must describe the same
	 * complete device. A shorter declared swap area cannot authorize writes
	 * to an otherwise unused partition tail.
	 */
	if ((unsigned long long)last_page != pages - 1U)
		return 0;

	for (index = 0; index < SWAPZ_LINUX_SWAP_MAGIC_BYTES; ++index)
		if (block[SWAPZ_SUPERBLOCK_BYTES -
			  SWAPZ_LINUX_SWAP_MAGIC_BYTES + index] != magic[index])
			return 0;

	/* A cleared Linux swap UUID is valid; PARTUUID binds physical identity. */
	return 1;
}

#endif
