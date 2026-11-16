/* SPDX-License-Identifier: GPL-2.0-only */
#ifndef SWAPZ_ZSWAP_DIRECT_HANDOFF_H
#define SWAPZ_ZSWAP_DIRECT_HANDOFF_H

/*
 * Experimental descriptor/readback contract; production integration is OFF.
 * This is not the existing swapz RAW, LZ4 or delta64 representation.
 * Descriptors live only in bounded RAM, never on SWAPSPACE2 media.
 * A producer must own an immutable payload copy until the consumer finishes;
 * scalar ownership fields cannot substitute for that producer-side lifetime.
 * No function here publishes an extent, completes I/O, or writes a device.
 */
#define SWAPZ_DIRECT_HANDOFF_PRODUCTION_ENABLED 0U
#define SWAPZ_DIRECT_HANDOFF_VERSION 1U
#define SWAPZ_DIRECT_LOGICAL_BYTES 4096U
#define SWAPZ_DIRECT_MAX_COMPRESSED_BYTES 3568U
#define SWAPZ_DIRECT_SHA256_BYTES 32U

#ifdef __KERNEL__
#include <linux/errno.h>
#include <linux/string.h>
#include <linux/types.h>
typedef u8 swapz_direct_u8;
typedef u32 swapz_direct_u32;
typedef u64 swapz_direct_u64;
#else
#include <errno.h>
#include <stdint.h>
#include <string.h>
typedef uint8_t swapz_direct_u8;
typedef uint32_t swapz_direct_u32;
typedef uint64_t swapz_direct_u64;
#endif

enum swapz_direct_origin {
	SWAPZ_DIRECT_ORDINARY_UNKNOWN = 0,
	SWAPZ_DIRECT_AUTHENTICATED_STORED = 1,
};

enum swapz_direct_representation {
	SWAPZ_DIRECT_FULL_PAGE = 0,
	SWAPZ_DIRECT_ZSWAP_COMPRESSED = 1,
};

enum swapz_direct_codec {
	SWAPZ_DIRECT_CODEC_UNKNOWN = 0,
	SWAPZ_DIRECT_ZSWAP_LZ4 = 1,
	SWAPZ_DIRECT_ZSWAP_ZSTD = 2,
};

enum swapz_direct_payload_lifetime {
	SWAPZ_DIRECT_BORROWED = 0,
	SWAPZ_DIRECT_IMMUTABLY_OWNED = 1,
};

/*
 * Expected identity comes from an independent, already-authenticated RAM
 * mapping under its generation/GC lock, not from the submitted descriptor.
 * Identity cookies are equality guards, NOT cryptographic authentication.
 */
struct swapz_direct_read_identity {
	swapz_direct_u64 logical_page;
	swapz_direct_u64 generation;
	swapz_direct_u64 source_record_identity;
};

struct swapz_direct_ram_descriptor {
	swapz_direct_u32 version;
	enum swapz_direct_origin semantic_origin;
	enum swapz_direct_representation representation;
	enum swapz_direct_codec codec;
	enum swapz_direct_payload_lifetime payload_lifetime;
	swapz_direct_u32 logical_bytes;
	swapz_direct_u32 compressed_length;
	swapz_direct_u64 logical_page;
	swapz_direct_u64 generation;
	swapz_direct_u64 source_record_identity;
	swapz_direct_u64 pool_identity;
	swapz_direct_u64 dictionary_identity;
	swapz_direct_u64 codec_generation;
	const swapz_direct_u8 *payload; /* [compressed_length], exclusively owned */
	swapz_direct_u32 payload_crc32c;
	swapz_direct_u8 expected_page_sha256[SWAPZ_DIRECT_SHA256_BYTES];
};

/* The registry must be resolved against the actual originating zswap codec,
 * pool/dictionary and compressor generation BEFORE accepting the WRITE.
 * Test decoders exercise this interface but do not prove Linux interoperability.
 */
typedef int (*swapz_direct_decode_fn)(
	const swapz_direct_u8 *compressed, swapz_direct_u32 compressed_length,
	swapz_direct_u8 *page, swapz_direct_u32 page_capacity,
	swapz_direct_u32 *decoded_length, void *context);
typedef int (*swapz_direct_crc32c_fn)(
	const swapz_direct_u8 *bytes, swapz_direct_u32 length,
	swapz_direct_u32 *digest, void *context);
typedef int (*swapz_direct_sha256_fn)(
	const swapz_direct_u8 *bytes, swapz_direct_u32 length,
	swapz_direct_u8 digest[SWAPZ_DIRECT_SHA256_BYTES], void *context);

struct swapz_direct_decoder {
	enum swapz_direct_codec codec;
	swapz_direct_u64 pool_identity;
	swapz_direct_u64 dictionary_identity;
	swapz_direct_u64 codec_generation;
	swapz_direct_decode_fn decode;
	void *context;
};

struct swapz_direct_integrity {
	swapz_direct_crc32c_fn crc32c;
	swapz_direct_sha256_fn sha256;
	void *context;
};

/*
 * Pure pre-admission check. Never turn this into a production eligibility
 * decision without a real protected producer source and matching decoder.
 * Caller owns synchronization; all inputs must remain immutable for the call.
 */
static inline int swapz_direct_validate(
	const struct swapz_direct_ram_descriptor *descriptor,
	const struct swapz_direct_read_identity *expected,
	const struct swapz_direct_decoder *decoder,
	const struct swapz_direct_integrity *integrity)
{
	swapz_direct_u32 index;
	swapz_direct_u8 digest_present = 0;

	if (!descriptor || !expected || !decoder || !integrity)
		return -EINVAL;
	if (descriptor->version != SWAPZ_DIRECT_HANDOFF_VERSION ||
	    descriptor->semantic_origin != SWAPZ_DIRECT_AUTHENTICATED_STORED ||
	    descriptor->representation != SWAPZ_DIRECT_ZSWAP_COMPRESSED ||
	    descriptor->payload_lifetime != SWAPZ_DIRECT_IMMUTABLY_OWNED ||
	    descriptor->logical_bytes != SWAPZ_DIRECT_LOGICAL_BYTES ||
	    !descriptor->payload || !descriptor->compressed_length ||
	    descriptor->compressed_length > SWAPZ_DIRECT_MAX_COMPRESSED_BYTES)
		return -EINVAL;
	if (descriptor->codec != SWAPZ_DIRECT_ZSWAP_LZ4 &&
	    descriptor->codec != SWAPZ_DIRECT_ZSWAP_ZSTD)
		return -EOPNOTSUPP;
	if (!expected->generation || !expected->source_record_identity ||
	    !descriptor->generation || !descriptor->source_record_identity ||
	    descriptor->logical_page != expected->logical_page ||
	    descriptor->generation != expected->generation ||
	    descriptor->source_record_identity != expected->source_record_identity)
		return -ESTALE;
	if (!descriptor->pool_identity || !descriptor->codec_generation ||
	    decoder->codec != descriptor->codec ||
	    decoder->pool_identity != descriptor->pool_identity ||
	    decoder->dictionary_identity != descriptor->dictionary_identity ||
	    decoder->codec_generation != descriptor->codec_generation ||
	    !decoder->decode || !integrity->crc32c || !integrity->sha256)
		return -EOPNOTSUPP;
	for (index = 0; index < SWAPZ_DIRECT_SHA256_BYTES; ++index)
		digest_present |= descriptor->expected_page_sha256[index];
	if (!digest_present)
		return -EBADMSG;
	return 0;
}

/*
 * Caller supplies a separate writable 4096-byte private scratch page and
 * output page. The output remains untouched on every error; scratch and
 * digest are cleared after use. This is a READ contract only: it does not
 * make a record authoritative. The provided SHA-256 callback must be a real
 * vetted digest implementation, with expected digest bound to the original
 * plaintext before compression. A test fixture callback is not proof of it.
 */
static inline int swapz_direct_readback(
	const struct swapz_direct_ram_descriptor *descriptor,
	const struct swapz_direct_read_identity *expected,
	const struct swapz_direct_decoder *decoder,
	const struct swapz_direct_integrity *integrity,
	swapz_direct_u8 *private_scratch, swapz_direct_u8 *output_page)
{
	swapz_direct_u8 page_digest[SWAPZ_DIRECT_SHA256_BYTES] = {0};
	swapz_direct_u32 crc = 0, decoded_bytes = 0, index;
	swapz_direct_u8 difference = 0;
	int status;

	if (!private_scratch || !output_page || private_scratch == output_page)
		return -EINVAL;
	status = swapz_direct_validate(descriptor, expected, decoder, integrity);
	if (status)
		goto clear;
	if (private_scratch == descriptor->payload || output_page == descriptor->payload) {
		status = -EINVAL;
		goto clear;
	}
	status = integrity->crc32c(descriptor->payload,
				    descriptor->compressed_length, &crc,
				    integrity->context);
	if (status || crc != descriptor->payload_crc32c) {
		status = -EBADMSG;
		goto clear;
	}
	status = decoder->decode(descriptor->payload,
				 descriptor->compressed_length, private_scratch,
				 SWAPZ_DIRECT_LOGICAL_BYTES, &decoded_bytes,
				 decoder->context);
	if (status || decoded_bytes != SWAPZ_DIRECT_LOGICAL_BYTES) {
		status = -EBADMSG;
		goto clear;
	}
	status = integrity->sha256(private_scratch, SWAPZ_DIRECT_LOGICAL_BYTES,
				  page_digest, integrity->context);
	if (status)
		goto clear;
	for (index = 0; index < SWAPZ_DIRECT_SHA256_BYTES; ++index)
		difference |= page_digest[index] ^ descriptor->expected_page_sha256[index];
	if (difference) {
		status = -EBADMSG;
		goto clear;
	}
	memcpy(output_page, private_scratch, SWAPZ_DIRECT_LOGICAL_BYTES);
	status = 0;
clear:
#ifdef __KERNEL__
	memzero_explicit(private_scratch, SWAPZ_DIRECT_LOGICAL_BYTES);
	memzero_explicit(page_digest, sizeof(page_digest));
#else
	memset(private_scratch, 0, SWAPZ_DIRECT_LOGICAL_BYTES);
	memset(page_digest, 0, sizeof(page_digest));
#endif
	return status;
}

#endif /* SWAPZ_ZSWAP_DIRECT_HANDOFF_H */
