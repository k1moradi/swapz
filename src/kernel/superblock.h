/* SPDX-License-Identifier: GPL-2.0-only */
#ifndef SWAPZ_SUPERBLOCK_H
#define SWAPZ_SUPERBLOCK_H

/*
 * On-media authorization header for explicitly formatted physical backing.
 * The kernel never writes this block. swapz data starts at physical block 1.
 * Keep this header freestanding so swapzctl and the kernel share one layout.
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
	       swapz_sb_uuid_nonzero(block);
}

#endif
