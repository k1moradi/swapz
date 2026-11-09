/* SPDX-License-Identifier: GPL-2.0-only */
#ifndef SWAPZ_SUPERBLOCK_H
#define SWAPZ_SUPERBLOCK_H

/*
 * Legacy synthetic SWZ authorization header (not a physical backing format).
 * Real backing retains its original Linux SWAPSPACE2 header unmodified.
 * The kernel reserves the first physical page; swapz data starts at block 1.
 * Keep this shared layout only for existing synthetic tests and safe handling
 * of historical interrupted transactions pending removal.
 */
#define SWAPZ_SUPERBLOCK_BYTES 4096U
#define SWAPZ_SUPERBLOCK_MAGIC_BYTES 8U
#define SWAPZ_SUPERBLOCK_VERSION 1U
#define SWAPZ_SUPERBLOCK_MAGIC_OFFSET 0U
#define SWAPZ_SUPERBLOCK_VERSION_OFFSET 8U
#define SWAPZ_SUPERBLOCK_HEADER_BYTES_OFFSET 12U
#define SWAPZ_SUPERBLOCK_DEVICE_BYTES_OFFSET 16U
#define SWAPZ_SUPERBLOCK_UUID_OFFSET 24U
#define SWAPZ_SUPERBLOCK_UUID_BYTES 16U
#define SWAPZ_SUPERBLOCK_RESERVED_OFFSET \
	(SWAPZ_SUPERBLOCK_UUID_OFFSET + SWAPZ_SUPERBLOCK_UUID_BYTES)

static const unsigned char swapz_superblock_magic[SWAPZ_SUPERBLOCK_MAGIC_BYTES] = {
	'S', 'W', 'A', 'P', 'Z', '0', '0', '1'
};

static inline void swapz_sb_put_u32(unsigned char *p, unsigned int value)
{
	p[0] = (unsigned char)value;
	p[1] = (unsigned char)(value >> 8);
	p[2] = (unsigned char)(value >> 16);
	p[3] = (unsigned char)(value >> 24);
}

static inline unsigned int swapz_sb_get_u32(const unsigned char *p)
{
	return (unsigned int)p[0] |
	       ((unsigned int)p[1] << 8) |
	       ((unsigned int)p[2] << 16) |
	       ((unsigned int)p[3] << 24);
}

static inline void swapz_sb_put_u64(unsigned char *p, unsigned long long value)
{
	unsigned int i;

	for (i = 0; i < 8U; ++i)
		p[i] = (unsigned char)(value >> (8U * i));
}

static inline unsigned long long swapz_sb_get_u64(const unsigned char *p)
{
	unsigned long long value = 0;
	unsigned int i;

	for (i = 0; i < 8U; ++i)
		value |= (unsigned long long)p[i] << (8U * i);
	return value;
}

static inline int swapz_sb_magic_matches(const unsigned char *block)
{
	unsigned int i;

	for (i = 0; i < SWAPZ_SUPERBLOCK_MAGIC_BYTES; ++i)
		if (block[SWAPZ_SUPERBLOCK_MAGIC_OFFSET + i] !=
		    swapz_superblock_magic[i])
			return 0;
	return 1;
}

static inline int swapz_sb_uuid_nonzero(const unsigned char *block)
{
	unsigned int i;
	unsigned char any = 0;

	for (i = 0; i < SWAPZ_SUPERBLOCK_UUID_BYTES; ++i)
		any |= block[SWAPZ_SUPERBLOCK_UUID_OFFSET + i];
	return any != 0;
}

/* Every byte after the UUID is reserved and must remain zero. */
static inline int swapz_sb_reserved_zero(const unsigned char *block)
{
	unsigned int i;

	for (i = SWAPZ_SUPERBLOCK_RESERVED_OFFSET;
	     i < SWAPZ_SUPERBLOCK_BYTES; ++i)
		if (block[i] != 0)
			return 0;
	return 1;
}

static inline int swapz_sb_valid(const unsigned char *block,
				 unsigned long long device_bytes)
{
	return swapz_sb_magic_matches(block) &&
	       swapz_sb_get_u32(block + SWAPZ_SUPERBLOCK_VERSION_OFFSET) ==
		       SWAPZ_SUPERBLOCK_VERSION &&
	       swapz_sb_get_u32(block + SWAPZ_SUPERBLOCK_HEADER_BYTES_OFFSET) ==
		       SWAPZ_SUPERBLOCK_BYTES &&
	       swapz_sb_get_u64(block + SWAPZ_SUPERBLOCK_DEVICE_BYTES_OFFSET) ==
		       device_bytes &&
	       swapz_sb_uuid_nonzero(block) &&
	       swapz_sb_reserved_zero(block);
}

/* A normal Linux swap partition remains formatted as SWAPSPACE2.
 * Its first page is a protected backing reservation, not SWZ metadata.
 * All swapz allocation/authority metadata is kept in RAM.
 */
#define SWAPZ_LINUX_SWAP_MAGIC_BYTES 10U
#define SWAPZ_LINUX_SWAP_VERSION_OFFSET 1024U
#define SWAPZ_LINUX_SWAP_LAST_PAGE_OFFSET 1028U
#define SWAPZ_LINUX_SWAP_BAD_PAGES_OFFSET 1032U
#define SWAPZ_LINUX_SWAP_UUID_OFFSET 1036U
#define SWAPZ_LINUX_SWAP_UUID_BYTES 16U

static inline int swapz_linux_swap_header_valid(
    const unsigned char *block, unsigned long long device_bytes)
{
    static const unsigned char magic[SWAPZ_LINUX_SWAP_MAGIC_BYTES] = {
        'S', 'W', 'A', 'P', 'S', 'P', 'A', 'C', 'E', '2'
    };
    unsigned long long pages = device_bytes / SWAPZ_SUPERBLOCK_BYTES;
    unsigned int last_page;
    unsigned int index;

    if (!block || device_bytes % SWAPZ_SUPERBLOCK_BYTES ||
        pages < 3U || pages > 0xffffffffULL ||
        swapz_sb_get_u32(block + SWAPZ_LINUX_SWAP_VERSION_OFFSET) != 1U ||
        swapz_sb_get_u32(block + SWAPZ_LINUX_SWAP_BAD_PAGES_OFFSET) != 0U)
        return 0;
    last_page = swapz_sb_get_u32(block + SWAPZ_LINUX_SWAP_LAST_PAGE_OFFSET);
    if (last_page < 2U || (unsigned long long)last_page >= pages)
        return 0;
    for (index = 0; index < SWAPZ_LINUX_SWAP_MAGIC_BYTES; ++index)
        if (block[SWAPZ_SUPERBLOCK_BYTES - SWAPZ_LINUX_SWAP_MAGIC_BYTES +
                  index] != magic[index])
            return 0;
    /* A Linux swap UUID is optional (for example, mkswap -U clear).
     * Admission must not mutate the existing signature or UUID bytes. */
    return 1;
}

#endif
