/* SPDX-License-Identifier: GPL-2.0-only */
#ifndef SWAPZ_EXTENT_CODEC_H
#define SWAPZ_EXTENT_CODEC_H

/*
 * Experimental unversioned 4/8/16 KiB extent FORMAT ONLY.
 *
 * Existing mappings or records from other disk formats are not interpreted as SWZ.
 * No extent is authoritative until its containing full-block write has
 * completed and the owning mapping transaction explicitly publishes it.
 * This is a codec, NOT an allocator, write path or GC implementation.
 */
#ifdef __KERNEL__
#include <linux/types.h>
typedef u8 swapz_u8;
typedef u16 swapz_u16;
typedef u32 swapz_u32;
#else
#include <stdint.h>
typedef uint8_t swapz_u8;
typedef uint16_t swapz_u16;
typedef uint32_t swapz_u32;
#endif

#define SWAPZ_BLOCK_BYTES 4096U
#define SWAPZ_BLOCK_SHIFT 12U
#define SWAPZ_MAX_BLOCKS 4U
#define SWAPZ_MAX_EXTENT_BYTES (SWAPZ_MAX_BLOCKS * SWAPZ_BLOCK_BYTES)
#define SWAPZ_MAX_RECORDS 64U
#define SWAPZ_MAX_COMPRESSED 3568U
#define SWAPZ_MAGIC 0x005a5753U /* little endian "SWZ\\0" */
#define SWAPZ_ENCODING_LZ4 0U
#define SWAPZ_ENCODING_DELTA64 1U
#define SWAPZ_RECORD_DELTA64_FLAG 0x8000U
#define SWAPZ_RECORD_LENGTH_MASK 0x7fffU

/* Endian encoding is little-endian, independently of the host CPU. */
struct swapz_header {
	swapz_u32 magic_le;
	swapz_u16 flags_le; /* reserved; zero until SWZ needs an extension */
	swapz_u8 extent_blocks;
	swapz_u8 record_count;
	swapz_u32 sequence_le;
	swapz_u32 metadata_crc32c_le;
} __attribute__((packed));

struct swapz_record {
	swapz_u32 logical_page_le;
	swapz_u32 generation_le;
	swapz_u16 payload_offset_le;
	swapz_u16 payload_length_le;
	swapz_u32 payload_crc32c_le;
} __attribute__((packed));

/* Host-side state is NEVER serialized or cast over disk memory. */
struct swapz_builder {
	swapz_u8 *bytes;
	swapz_u32 bytes_total;
	swapz_u16 payload_start;
	swapz_u8 extent_blocks;
	swapz_u8 count;
	swapz_u32 sequence;
	int sealed;
};

struct swapz_decoded {
	swapz_u32 logical_page;
	swapz_u32 generation;
	swapz_u32 payload_crc32c;
	swapz_u16 payload_offset;
	swapz_u16 payload_length;
	swapz_u8 encoding;
};

int swapz_begin(struct swapz_builder *builder, void *bytes,
	      swapz_u32 bytes_total, swapz_u32 sequence);
int swapz_append(struct swapz_builder *builder, swapz_u32 logical_page,
	       swapz_u32 generation, const void *payload, swapz_u16 length);
int swapz_append_prehashed(struct swapz_builder *builder,
		       swapz_u32 logical_page, swapz_u32 generation,
		       const void *payload, swapz_u16 length,
		       swapz_u32 payload_crc32c);
int swapz_append_encoded(struct swapz_builder *builder,
		       swapz_u32 logical_page, swapz_u32 generation,
		       const void *payload, swapz_u16 length,
		       swapz_u8 encoding);
int swapz_append_prehashed_encoded(struct swapz_builder *builder,
		       swapz_u32 logical_page, swapz_u32 generation,
		       const void *payload, swapz_u16 length,
		       swapz_u32 payload_crc32c, swapz_u8 encoding);
int swapz_seal(struct swapz_builder *builder);
int swapz_validate(const void *bytes, swapz_u32 bytes_total);
/*
 * Reads/verifies ONLY metadata (block zero contains at most 1040 metadata
 * bytes). The caller may then fetch just the target record's payload blocks.
 */
int swapz_peek(const void *bytes, swapz_u32 bytes_total, swapz_u8 index,
	     struct swapz_decoded *out);
int swapz_lookup(const void *bytes, swapz_u32 bytes_total, swapz_u8 index,
	       struct swapz_decoded *out, const swapz_u8 **payload);
/* Caller must have already completed swapz_validate() on this immutable image.
 * Descriptor lookup retains defensive bounds checks but deliberately does not
 * hash the payload. It exists so authority publication can time ONLY the final
 * payload CRC without weakening the public validated lookup contract. */
int swapz_lookup_validated_descriptor(const void *bytes, swapz_u32 bytes_total,
				    swapz_u8 index, struct swapz_decoded *out,
				    const swapz_u8 **payload);
/* Caller must have already completed swapz_validate() on this immutable image.
 * This still verifies the selected final payload CRC before returning it. */
int swapz_lookup_validated(const void *bytes, swapz_u32 bytes_total,
			 swapz_u8 index, struct swapz_decoded *out,
			 const swapz_u8 **payload);
swapz_u32 swapz_crc32c_bytes(const void *bytes, swapz_u32 length);

#endif
