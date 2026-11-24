/* SPDX-License-Identifier: GPL-2.0-only */
#ifndef SWAPZ_ORIGINAL_EXTENT_H
#define SWAPZ_ORIGINAL_EXTENT_H

#include "codec.h"

#define SWAPZ_ORIGINAL_EXTENT_ACTIVE 0U

#ifdef SWAPZ_ORIGINAL_EXTENT_TEST
/* Separate original codec namespace, never ordinary predictor/RAW flags.
 * These values follow the frozen logical profile, not a deployed ABI. */
#define SWAPZ_ORIGINAL_EXTENT_REPRESENTATION 0x5aU
#define SWAPZ_ORIGINAL_EXTENT_LZ4 1U
#define SWAPZ_ORIGINAL_EXTENT_LZO1X 2U
#define SWAPZ_ORIGINAL_EXTENT_VERSION 1U
#define SWAPZ_ORIGINAL_EXTENT_CONSERVATIVE SWAPZ_MAX_COMPRESSED
#define SWAPZ_ORIGINAL_EXTENT_EXPERIMENTAL (SWAPZ_BLOCK_BYTES - 1U)
#define SWAPZ_ORIGINAL_EXTENT_DEDICATED 1U
#define SWAPZ_ORIGINAL_EXTENT_PACKED 2U

/* Caller supplies already-validated authority and immutable bytes.
 * CRC is supplied independently and checked, not source authentication.
 * Logical page zero is geometry-valid; generation zero is not. */
struct swapz_original_extent_input {
	const swapz_u8 *bytes;
	swapz_u32 bytes_available;
	swapz_u32 logical_page;
	swapz_u32 generation;
	swapz_u32 length;
	swapz_u32 decoded_length;
	swapz_u32 crc32c;
	swapz_u8 representation;
	swapz_u8 codec;
	swapz_u8 version;
	swapz_u8 dictionary_id;
};

/* Entirely volatile descriptor. Offsets and read ranges are extent-relative. */
struct swapz_original_extent_record {
	swapz_u32 logical_page;
	swapz_u32 generation;
	swapz_u32 crc32c;
	swapz_u16 offset;
	swapz_u16 length;
	swapz_u8 representation;
	swapz_u8 codec;
	swapz_u8 version;
	swapz_u8 first_block;
	swapz_u8 read_blocks;
	swapz_u8 reserved[3];
};

/* Caller owns exact image and contiguous descriptor storage exclusively.
 * No allocation, locks, I/O or publication. Serialize calls; don't modify
 * builder or records between calls. After seal keep the image immutable
 * until its eventual external I/O owner is done. No MM or decoder lease. */
struct swapz_original_extent {
	swapz_u8 *image;
	struct swapz_original_extent_record *records;
	swapz_u32 image_bytes;
	swapz_u32 occupied_bytes;
	swapz_u32 unused_bytes;
	swapz_u32 ceiling;
	swapz_u32 capacity;
	swapz_u32 count;
	swapz_u8 mode;
	swapz_u8 sealed;
};

/* On any failed preflight, image, records, builder and plan output unchanged.
 * record_bytes must be exactly capacity * sizeof(*records). Dedicated uses
 * offset zero and suffix padding; packed uses descending offsets and prefix
 * padding. No per-record padding. begin does not touch image or records. */
int swapz_original_extent_begin(struct swapz_original_extent *extent,
	void *image, swapz_u32 image_bytes,
	struct swapz_original_extent_record *records, swapz_u32 record_bytes,
	swapz_u32 capacity, swapz_u32 ceiling, swapz_u8 mode);
int swapz_original_extent_plan(const struct swapz_original_extent *extent,
	const struct swapz_original_extent_input *input,
	struct swapz_original_extent_record *result);
int swapz_original_extent_append(struct swapz_original_extent *extent,
	const struct swapz_original_extent_input *input);
int swapz_original_extent_seal(struct swapz_original_extent *extent);
#endif
#endif
