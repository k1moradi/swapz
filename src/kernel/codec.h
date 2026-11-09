/* SPDX-License-Identifier: GPL-2.0-only */
#ifndef SWAPZ_EXTENT_CODEC_H
#define SWAPZ_EXTENT_CODEC_H

/*
 * Legacy 4/8/16 KiB in-band extent codec (RAM-only metadata migration pending).
 *
 * This header defines the existing compressed extent representation, NOT a
 * backing partition format: real backing must remain preformatted SWAPSPACE2.
 * Current serialized SWZ extent headers and descriptors are nonconforming with
 * the owner-mandated RAM-only metadata design and must be replaced together
 * with the read, pack, publication and GC paths. Until then, no extent is
 * authoritative before confirmed full-block write and ordered publication.
 * This is a codec, NOT an allocator, write path or GC implementation.
 */
#ifdef __KERNEL__
#include <linux/types.h>
typedef u8 swapz_u8;
typedef u16 swapz_u16;
typedef u32 swapz_u32;
typedef u64 swapz_u64;
#else
#include <stdint.h>
typedef uint8_t swapz_u8;
typedef uint16_t swapz_u16;
typedef uint32_t swapz_u32;
typedef uint64_t swapz_u64;
#endif

/*
 * Production compressed lower images are payload-only: all swapz descriptors,
 * offsets, lengths, encodings, generations, sequences and CRCs are volatile
 * RAM authority. The legacy codec below remains only for historical/native
 * regression fixtures and must never define physical backing identity.
 */
#define SWAPZ_CODEC_METADATA_ON_MEDIA 0U

#define SWAPZ_BLOCK_BYTES 4096U
#define SWAPZ_BLOCK_SHIFT 12U
#define SWAPZ_MAX_BLOCKS 4U
#define SWAPZ_MAX_EXTENT_BYTES (SWAPZ_MAX_BLOCKS * SWAPZ_BLOCK_BYTES)
#define SWAPZ_MAX_RECORDS 64U
#define SWAPZ_MAX_COMPRESSED 3568U
#define SWAPZ_MAGIC 0x005a5753U /* little endian "SWZ\\0" */
#define SWAPZ_ENCODING_LZ4 0U
#define SWAPZ_ENCODING_DELTA64 1U
/* delta64, then 8-byte byte-plane shuffle (predictor-shuffle.h), then LZ4. */
#define SWAPZ_ENCODING_DELTA64_SHUF8 2U
/* Decoded only from a reserved flag combination; never valid. */
#define SWAPZ_ENCODING_INVALID 0xffU
/*
 * payload_length_le: bits 0..13 length (<= SWAPZ_MAX_COMPRESSED), bit 15
 * delta64, bit 14 byte-plane shuffle. Bit 14 without bit 15 is reserved and
 * rejected by validation.
 */
#define SWAPZ_RECORD_DELTA64_FLAG 0x8000U
#define SWAPZ_RECORD_SHUF8_FLAG 0x4000U
#define SWAPZ_RECORD_LENGTH_MASK 0x3fffU

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

/* Bounded in-RAM snapshot for the legacy codec's 16-byte header and up to
 * 64 descriptors. The descriptor image is never part of the detached lower
 * payload; the target must maintain its own lifetime/transaction ownership
 * across asynchronous writes, reads and garbage collection.
 */
#define SWAPZ_MAX_METADATA_BYTES \
	(sizeof(struct swapz_header) + \
	 SWAPZ_MAX_RECORDS * sizeof(struct swapz_record))

struct swapz_ram_extent_metadata {
	swapz_u16 length;
	swapz_u8 bytes[SWAPZ_MAX_METADATA_BYTES];
};

/* Host-side state is NEVER serialized or cast over disk memory. */
struct swapz_builder {
	swapz_u8 *bytes;
	swapz_u32 bytes_total;
	swapz_u16 payload_start;
	swapz_u8 extent_blocks;
	swapz_u8 count;
	swapz_u32 sequence;
	/* Last appended record metadata is host-side only. Production binds
	 * these fields into the staged RAM transaction before lower I/O. */
	swapz_u32 last_payload_crc32c;
	swapz_u16 last_payload_offset;
	swapz_u16 last_payload_length;
	swapz_u8 last_encoding;
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

/*
 * Builder owns an exclusive, writable bytes_total-byte extent until seal.
 * Append inputs own at least length readable bytes; inputs overlapping that
 * extent are rejected with -EINVAL (memcpy is not memmove). Unaligned buffers
 * are supported. No builder
 * operation is safe concurrently with mutation or consumption of that extent.
 */
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
/* Internal production fast path: skip only the duplicate-logical scan after
 * the caller has proved window-wide uniqueness. Payload validation and CRC32C
 * remain codec-owned and happen before any record mutation. */
int swapz_append_encoded_unique(struct swapz_builder *builder,
		       swapz_u32 logical_page, swapz_u32 generation,
		       const void *payload, swapz_u16 length,
		       swapz_u8 encoding);
int swapz_append_prehashed_encoded(struct swapz_builder *builder,
		       swapz_u32 logical_page, swapz_u32 generation,
		       const void *payload, swapz_u16 length,
		       swapz_u32 payload_crc32c, swapz_u8 encoding);
/* Internal production fast path: the caller has already proved this logical
 * page is unique across the builder's immutable batch. All other validation,
 * capacity checks and payload writes remain identical to the generic append. */
int swapz_append_prehashed_encoded_unique(struct swapz_builder *builder,
		       swapz_u32 logical_page, swapz_u32 generation,
		       const void *payload, swapz_u16 length,
		       swapz_u32 payload_crc32c, swapz_u8 encoding);
int swapz_seal(struct swapz_builder *builder);
/* The exclusively owned, sealed extent remains a data-only lower image
 * after detach: the exact descriptor prefix is zeroed and retained in RAM.
 * Reattachment is for an exclusively owned RAM read/validation scratch ONLY,
 * never for a lower I/O buffer. Neither operation performs lower I/O or
 * publishes a mapping. Caller controls snapshot lifetime and synchronization.
 *
 * Failures do not modify extent contents or the supplied RAM metadata.
 * An attached image must have the same size/class as the original and an
 * all-zero descriptor prefix, or reattachment is refused.
 */
int swapz_detach_extent_metadata(
	struct swapz_builder *builder, struct swapz_ram_extent_metadata *metadata);
int swapz_attach_extent_metadata(
	void *extent, swapz_u32 bytes_total,
	const struct swapz_ram_extent_metadata *metadata);
/* Validate extent/header identity plus the metadata CRC only. Descriptor
 * semantic checks remain the caller's responsibility unless swapz_validate()
 * is used. This exists for publication paths that already walk every record. */
int swapz_validate_metadata_crc(const void *bytes, swapz_u32 bytes_total);
int swapz_validate(const void *bytes, swapz_u32 bytes_total);
/*
 * Reads/verifies ONLY metadata (block zero contains at most 1040 metadata
 * bytes). The caller may then fetch just the target record's payload blocks.
 */
int swapz_peek(const void *bytes, swapz_u32 bytes_total, swapz_u8 index,
	     struct swapz_decoded *out);
int swapz_lookup(const void *bytes, swapz_u32 bytes_total, swapz_u8 index,
	       struct swapz_decoded *out, const swapz_u8 **payload);
/* Caller must have authenticated immutable metadata with swapz_validate() or
 * swapz_validate_metadata_crc(). Descriptor lookup retains defensive bounds
 * checks, including nonzero generation and payload/metadata separation, but
 * deliberately does not hash the payload. payload may be NULL for metadata-only
 * storage; when non-NULL, bytes must span bytes_total so the returned pointer
 * names resident payload bytes. A metadata-CRC-only caller must still enforce
 * descriptor ordering/identity itself. A malformed record count is -EUCLEAN;
 * -ERANGE is reserved for an index outside an otherwise valid count. */
int swapz_lookup_validated_descriptor(const void *bytes, swapz_u32 bytes_total,
				    swapz_u8 index, struct swapz_decoded *out,
				    const swapz_u8 **payload);
/* Caller must have already completed swapz_validate() on this immutable image.
 * This still verifies the selected final payload CRC before returning it. */
int swapz_lookup_validated(const void *bytes, swapz_u32 bytes_total,
			 swapz_u8 index, struct swapz_decoded *out,
			 const swapz_u8 **payload);
swapz_u32 swapz_crc32c_bytes(const void *bytes, swapz_u32 length);

/*
 * Data-only compressed extent builder. The `bytes` buffer is the exact
 * lower-write image: no SWZ header, record table or other swapz metadata is
 * serialized to it. The caller owns both buffers exclusively until seal and
 * completed lower I/O; records must remain in bounded volatile RAM.
 *
 * A sealed builder is not persistent authority. The ordered engine must
 * publish verified descriptors into its authoritative RAM mappings only
 * after successful lower completion, and reject them on target teardown.
 * The read helper below is scratch-local and cannot reconstruct lost maps.
 */
struct swapz_ram_extent {
	swapz_u8 *bytes;                /* [bytes_total] lower-write payload area */
	struct swapz_decoded *records;  /* [record_capacity] volatile descriptors */
	swapz_u32 bytes_total;
	swapz_u32 sequence;             /* volatile, never written to bytes */
	swapz_u16 payload_start;
	swapz_u8 record_capacity;
	swapz_u8 extent_blocks;
	swapz_u8 count;
	swapz_u8 sealed;
};

int swapz_ram_extent_begin(struct swapz_ram_extent *builder, void *bytes,
			   swapz_u32 bytes_total, swapz_u32 sequence,
			   struct swapz_decoded *records, swapz_u8 record_capacity);
int swapz_ram_extent_append(struct swapz_ram_extent *builder,
			    swapz_u32 logical_page, swapz_u32 generation,
			    const void *payload, swapz_u16 payload_length,
			    swapz_u8 encoding);
/* Production fast path after the caller has proved logical-page uniqueness for
 * the complete packing window. Bounds, overlap and payload-integrity checks are
 * unchanged; only the redundant bounded duplicate scan is skipped. */
int swapz_ram_extent_append_unique(struct swapz_ram_extent *builder,
				   swapz_u32 logical_page,
				   swapz_u32 generation,
				   const void *payload,
				   swapz_u16 payload_length,
				   swapz_u8 encoding);
int swapz_ram_extent_append_prehashed(struct swapz_ram_extent *builder,
				      swapz_u32 logical_page,
				      swapz_u32 generation, const void *payload,
				      swapz_u16 payload_length,
				      swapz_u32 payload_crc32c, swapz_u8 encoding);
int swapz_ram_extent_append_prehashed_unique(
				      struct swapz_ram_extent *builder,
				      swapz_u32 logical_page,
				      swapz_u32 generation, const void *payload,
				      swapz_u16 payload_length,
				      swapz_u32 payload_crc32c,
				      swapz_u8 encoding);
int swapz_ram_extent_seal(struct swapz_ram_extent *builder);
/* Payload pointer remains valid only while the sealed staging buffer lives.
 * Verify independently authoritative logical/generation identity and CRC;
 * never trust a mutable scratch descriptor across concurrent publication. */
int swapz_ram_extent_read(const struct swapz_ram_extent *builder,
			  swapz_u8 record_index, swapz_u32 logical_page,
			  swapz_u32 generation, const swapz_u8 **payload);

#endif
