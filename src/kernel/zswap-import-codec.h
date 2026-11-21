/* SPDX-License-Identifier: GPL-2.0-only */
#ifndef SWAPZ_ZSWAP_IMPORT_CODEC_H
#define SWAPZ_ZSWAP_IMPORT_CODEC_H

/*
 * Source-only imported zswap original LZ4/LZO1X block profiles. No production source
 * includes this header. Metadata and authority exist ONLY in volatile RAM;
 * physical lower extents contain payload bytes and deterministic padding.
 * This is NOT an ordinary RAW_4096 record and never changes SWAPSPACE2.
 */
#define SWAPZ_ZSWAP_IMPORT_ACTIVE 0U
#define SWAPZ_ZSWAP_IMPORT_REPRESENTATION 0x5aU
#define SWAPZ_ZSWAP_IMPORT_LZ4_CODEC 1U
#define SWAPZ_ZSWAP_IMPORT_VERSION 1U
/* Independently tagged original Linux lzo-scomp / lib/lzo LZO1X v1. */
#define SWAPZ_ZSWAP_IMPORT_LZO1X_CODEC 2U
#define SWAPZ_ZSWAP_IMPORT_LZO1X_VERSION 1U

#include "codec.h"
#ifdef SWAPZ_ZSWAP_IMPORT_HOST_TEST
#include <errno.h>
#include <limits.h>
#include <lz4.h>
/* Generic host fixtures are LZ4-only; original LZO is an explicit opt-in. */
#ifdef SWAPZ_ZSWAP_IMPORT_ORIGINAL_LZO_HOST_TEST
#include <linux/lzo.h>
#endif
#include <openssl/sha.h>
#include <stddef.h>
#include <string.h>
#else
#include <crypto/sha2.h>
#include <linux/errno.h>
#include <linux/lz4.h>
#include <linux/lzo.h>
#include <linux/string.h>
#endif

/* A descriptor is immutable after its owner publishes this RAM snapshot. */
struct swapz_zswap_import_record {
	swapz_u64 logical_page;
	swapz_u64 generation;
	swapz_u64 stored_entry_identity;
	swapz_u64 store_generation;
	swapz_u64 gc_epoch;
	swapz_u32 compressed_length;
	swapz_u32 decoded_length;
	swapz_u32 compressed_crc32c;
	swapz_u8 original_sha256[32];
	swapz_u8 representation;
	swapz_u8 codec;
	swapz_u8 version;
	swapz_u8 dictionary_id; /* Only dictionary-free original LZ4/LZO1X. */
	swapz_u8 stored_eviction;
	swapz_u8 immutable_owned_copy;
};

/* Independently read from the current authoritative mapping and lower I/O. */
struct swapz_zswap_import_read_authority {
	swapz_u64 logical_page;
	swapz_u64 generation;
	swapz_u64 stored_entry_identity;
	swapz_u64 store_generation;
	swapz_u64 gc_epoch;
	swapz_u32 actual_lower_read_bytes;
	int lower_read_error;
	swapz_u8 mapping_published_after_durable_write;
	swapz_u8 foreground_write_committed_once;
	swapz_u8 upper_write_ack_count;
	swapz_u8 current_owned_ram_session;
	swapz_u8 teardown_started;
	swapz_u8 upper_read_ack_count;
};

/* Pointer ranges are checked without dereferencing or pointer ordering UB. */
static inline int swapz_zswap_import_ranges_overlap(const void *first,
		unsigned int first_length, const void *second,
		unsigned int second_length)
{
	const unsigned long first_address = (unsigned long)first;
	const unsigned long second_address = (unsigned long)second;

	return first_address <= second_address ?
		second_address - first_address < first_length :
		first_address - second_address < second_length;
}

static inline int swapz_zswap_import_sha256(const swapz_u8 *bytes,
					     swapz_u8 digest[32])
{
#ifdef SWAPZ_ZSWAP_IMPORT_HOST_TEST
	return SHA256(bytes, SWAPZ_BLOCK_BYTES, digest) ? 0 : -EIO;
#else
	sha256(bytes, SWAPZ_BLOCK_BYTES, digest);
	return 0;
#endif
}

/*
 * Caller owns separate 4096-byte scratch/output arrays and the sealed
 * compressed buffer during this synchronous call. Neither scratch nor output
 * may alias input. On error, output remains unchanged and upper completion
 * MUST propagate this negative errno. No allocation, lower I/O or ACK here.
 */
static inline int swapz_zswap_import_decode(
		const struct swapz_zswap_import_record *record,
		const struct swapz_zswap_import_read_authority *authority,
		const swapz_u8 *compressed_bytes, swapz_u32 compressed_capacity,
		swapz_u8 *scratch, swapz_u32 scratch_capacity,
		swapz_u8 *output, swapz_u32 output_capacity,
		const swapz_u8 *independent_original_page)
{
	swapz_u8 calculated_sha256[32];
	int decoded_bytes;
	int original_lzo1x;
	unsigned int offset;
	swapz_u8 digest_difference = 0;

	if (!record || !authority || !compressed_bytes || !scratch || !output)
		return -EINVAL;
	/*
	 * The codec identity MUST originate from a separately authenticated
	 * original selected driver, not a zswap pool name or inferred payload.
	 * This dormant function cannot itself authenticate a live source slot.
	 */
	original_lzo1x = record->codec == SWAPZ_ZSWAP_IMPORT_LZO1X_CODEC;
	if (record->representation != SWAPZ_ZSWAP_IMPORT_REPRESENTATION ||
	    (record->codec != SWAPZ_ZSWAP_IMPORT_LZ4_CODEC && !original_lzo1x) ||
	    (original_lzo1x ?
	     record->version != SWAPZ_ZSWAP_IMPORT_LZO1X_VERSION :
	     record->version != SWAPZ_ZSWAP_IMPORT_VERSION) ||
	    record->dictionary_id != 0U || !record->stored_eviction ||
	    !record->immutable_owned_copy)
		return -EOPNOTSUPP;
	if (!record->logical_page || !record->generation ||
	    !record->stored_entry_identity || !record->store_generation ||
	    !record->gc_epoch || !record->compressed_length ||
	    record->compressed_length > SWAPZ_MAX_COMPRESSED ||
	    record->decoded_length != SWAPZ_BLOCK_BYTES ||
	    compressed_capacity < record->compressed_length ||
	    scratch_capacity != SWAPZ_BLOCK_BYTES ||
	    output_capacity != SWAPZ_BLOCK_BYTES)
		return -EMSGSIZE;
	if (authority->logical_page != record->logical_page ||
	    authority->generation != record->generation ||
	    authority->stored_entry_identity != record->stored_entry_identity ||
	    authority->store_generation != record->store_generation ||
	    authority->gc_epoch != record->gc_epoch ||
	    !authority->mapping_published_after_durable_write ||
	    !authority->foreground_write_committed_once ||
	    authority->upper_write_ack_count != 1U ||
	    !authority->current_owned_ram_session || authority->teardown_started ||
	    authority->upper_read_ack_count)
		return -ESTALE;
	if (authority->lower_read_error)
		return -EIO;
	if (authority->actual_lower_read_bytes != record->compressed_length)
		return -EIO;
	if (swapz_zswap_import_ranges_overlap(scratch, SWAPZ_BLOCK_BYTES,
			output, SWAPZ_BLOCK_BYTES) ||
	    swapz_zswap_import_ranges_overlap(scratch, SWAPZ_BLOCK_BYTES,
			compressed_bytes, record->compressed_length) ||
	    swapz_zswap_import_ranges_overlap(output, SWAPZ_BLOCK_BYTES,
			compressed_bytes, record->compressed_length))
		return -EINVAL;
	if (swapz_crc32c_bytes(compressed_bytes, record->compressed_length) !=
	    record->compressed_crc32c)
		return -EBADMSG;
	if (original_lzo1x) {
#if !defined(SWAPZ_ZSWAP_IMPORT_HOST_TEST) || \
    defined(SWAPZ_ZSWAP_IMPORT_ORIGINAL_LZO_HOST_TEST)
		/*
		 * Exact original lib/lzo/lzo1x_decompress_safe.c byte stream,
		 * independently callable without a retired zswap pool/tfm. Original
		 * LZO_E_INPUT_NOT_CONSUMED and short output both fail closed.
		 * This direct symbol still requires a real kernel decoder/module
		 * lifetime lease before any future production read admission.
		 */
		size_t original_decoded_bytes = SWAPZ_BLOCK_BYTES;
		int result = lzo1x_decompress_safe(compressed_bytes,
				record->compressed_length, scratch,
				&original_decoded_bytes);

		if (result != LZO_E_OK ||
		    original_decoded_bytes != SWAPZ_BLOCK_BYTES)
			return -EBADMSG;
#else
		/* No original Linux decoder was linked by generic LZ4 host tests. */
		return -EOPNOTSUPP;
#endif
	} else {
		/* Raw LZ4 block, never framed LZ4 or original LZO1X bytes. */
		decoded_bytes = LZ4_decompress_safe((const char *)compressed_bytes,
				(char *)scratch, (int)record->compressed_length,
				(int)SWAPZ_BLOCK_BYTES);
		if (decoded_bytes != (int)SWAPZ_BLOCK_BYTES)
			return -EBADMSG;
	}
	if (swapz_zswap_import_sha256(scratch, calculated_sha256))
		return -EIO;
	for (offset = 0; offset < sizeof(calculated_sha256); ++offset)
		digest_difference |= calculated_sha256[offset] ^
			record->original_sha256[offset];
	if (digest_difference || (independent_original_page &&
	    memcmp(scratch, independent_original_page, SWAPZ_BLOCK_BYTES)))
		return -EBADMSG;
	memcpy(output, scratch, SWAPZ_BLOCK_BYTES);
	return 0;
}

#endif /* SWAPZ_ZSWAP_IMPORT_CODEC_H */
