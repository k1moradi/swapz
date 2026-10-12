/* SPDX-License-Identifier: GPL-2.0-only */
#ifndef SWAPZ_V3_EXTENT_CODEC_H
#define SWAPZ_V3_EXTENT_CODEC_H

/*
 * Experimental VERSIONED 4/8/16 KiB extent FORMAT ONLY.
 *
 * No existing dm-swapz mappings or V2.2 disk records are interpreted as V3.
 * No extent is authoritative until its containing full-block write has
 * completed and the owning mapping transaction explicitly publishes it.
 * This is a codec, NOT an allocator, write path or GC implementation.
 */
#ifdef __KERNEL__
#include <linux/types.h>
typedef u8 sv3_u8;
typedef u16 sv3_u16;
typedef u32 sv3_u32;
#else
#include <stdint.h>
typedef uint8_t sv3_u8;
typedef uint16_t sv3_u16;
typedef uint32_t sv3_u32;
#endif

#define SV3_BLOCK_BYTES 4096U
#define SV3_MAX_BLOCKS 4U
#define SV3_MAX_EXTENT_BYTES (SV3_MAX_BLOCKS * SV3_BLOCK_BYTES)
#define SV3_MAX_RECORDS 64U
#define SV3_MAX_COMPRESSED 3568U
#define SV3_MAGIC 0x335a5753U /* little endian "SWZ3" */
#define SV3_VERSION 3U

/* Endian encoding is little-endian, independently of the host CPU. */
struct sv3_header {
	sv3_u32 magic_le;
	sv3_u16 version_le;
	sv3_u8 extent_blocks;
	sv3_u8 record_count;
	sv3_u32 sequence_le;
	sv3_u32 metadata_crc32c_le;
} __attribute__((packed));

struct sv3_record {
	sv3_u32 logical_page_le;
	sv3_u32 generation_le;
	sv3_u16 payload_offset_le;
	sv3_u16 payload_length_le;
	sv3_u32 payload_crc32c_le;
} __attribute__((packed));

/* Host-side state is NEVER serialized or cast over disk memory. */
struct sv3_builder {
	sv3_u8 *bytes;
	sv3_u32 bytes_total;
	sv3_u16 payload_start;
	sv3_u8 extent_blocks;
	sv3_u8 count;
	sv3_u32 sequence;
	int sealed;
};

struct sv3_decoded {
	sv3_u32 logical_page;
	sv3_u32 generation;
	sv3_u32 payload_crc32c;
	sv3_u16 payload_offset;
	sv3_u16 payload_length;
};

int sv3_begin(struct sv3_builder *builder, void *bytes,
	      sv3_u32 bytes_total, sv3_u32 sequence);
int sv3_append(struct sv3_builder *builder, sv3_u32 logical_page,
	       sv3_u32 generation, const void *payload, sv3_u16 length);
int sv3_seal(struct sv3_builder *builder);
int sv3_validate(const void *bytes, sv3_u32 bytes_total);
/*
 * Reads/verifies ONLY metadata (block zero contains at most 1040 metadata
 * bytes). The caller may then fetch just the target record's payload blocks.
 */
int sv3_peek(const void *bytes, sv3_u32 bytes_total, sv3_u8 index,
	     struct sv3_decoded *out);
int sv3_lookup(const void *bytes, sv3_u32 bytes_total, sv3_u8 index,
	       struct sv3_decoded *out, const sv3_u8 **payload);
int sv3_record_read_blocks(const struct sv3_decoded *record);
sv3_u32 sv3_crc32c_bytes(const void *bytes, sv3_u32 length);

#endif
