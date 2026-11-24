/* SPDX-License-Identifier: GPL-2.0-only */
#ifndef SWAPZ_ZSWAP_ORIGINAL_DECODE_H
#define SWAPZ_ZSWAP_ORIGINAL_DECODE_H

#include "zswap-import-decoder-owner.h"

#define SWAPZ_ORIGINAL_DECODE_M3568 3568U
#define SWAPZ_ORIGINAL_DECODE_M4095 4095U

/* Volatile, immutable byte descriptor, not a mapping or receipt. The digest
 * must come from the separately authenticated original uncompressed page.
 * Numeric codec 2 here means original LZO1X, never legacy direct ZSTD. */
struct swapz_original_decode_record {
	swapz_u32 compressed_length;
	swapz_u32 decoded_length;
	swapz_u32 compressed_crc32c;
	swapz_u8 original_sha256[32];
	swapz_u8 representation;
	swapz_u8 codec;
	swapz_u8 version;
	swapz_u8 dictionary_id;
};

/* Geometry alone does not imply that a valid codec stream exists. */
int swapz_original_decode_length_valid(swapz_u32 ceiling, swapz_u32 length);

/* Synchronous opt-in candidate, not wired into any production call site.
 * Caller must already hold a genuine exclusive reader lease (obtained via
 * owner_get, not copied/forged), retain the independent decoder/module and
 * immutable original bytes/record, and serialize put after this call. Owner
 * storage remains live; close may drain concurrently but cannot revoke an
 * existing reader. Source/selected-DM authentication is an external gate.
 * All accessed ranges (record including digest, lease, owner, input,
 * scratch and output) must be disjoint and actually backed by their declared
 * spans. Scratch/output are exactly one page each; input capacity covers
 * compressed_length. Scratch can change on failure; output never changes
 * unless both exact decode and integrity checks succeed. No allocation,
 * lower I/O, mapping, recompression, publication or ACK is performed. */
int swapz_original_decode(
	const struct swapz_zswap_import_decoder_lease *lease,
	const struct swapz_original_decode_record *record, swapz_u32 ceiling,
	const swapz_u8 *input, swapz_u32 input_capacity,
	swapz_u8 *scratch, swapz_u32 scratch_capacity,
	swapz_u8 *output, swapz_u32 output_capacity);

#endif /* SWAPZ_ZSWAP_ORIGINAL_DECODE_H */
