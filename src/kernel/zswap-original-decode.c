// SPDX-License-Identifier: GPL-2.0-only
#include "zswap-original-decode.h"

int swapz_original_decode_length_valid(swapz_u32 ceiling, swapz_u32 length)
{
	return (ceiling == SWAPZ_ORIGINAL_DECODE_M3568 ||
		ceiling == SWAPZ_ORIGINAL_DECODE_M4095) &&
		length != 0U && length <= ceiling;
}

struct swapz_original_decode_range {
	const void *address;
	swapz_u32 length;
};

static int swapz_original_decode_disjoint(
	const struct swapz_zswap_import_decoder_lease *lease,
	const struct swapz_original_decode_record *record,
	const swapz_u8 *input, swapz_u8 *scratch, swapz_u8 *output)
{
	const struct swapz_original_decode_range ranges[] = {
		{record, (swapz_u32)sizeof(*record)},
		{lease, (swapz_u32)sizeof(*lease)},
		{lease->owner, (swapz_u32)sizeof(*lease->owner)},
		{input, record->compressed_length},
		{scratch, SWAPZ_BLOCK_BYTES},
		{output, SWAPZ_BLOCK_BYTES},
	};
	unsigned int first, second;
	const unsigned int count = sizeof(ranges) / sizeof(ranges[0]);

	for (first = 0U; first < count; ++first) {
		for (second = first + 1U; second < count; ++second) {
			if (swapz_zswap_import_ranges_overlap(ranges[first].address,
				ranges[first].length, ranges[second].address,
				ranges[second].length))
				return 0;
		}
	}
	return 1;
}

int swapz_original_decode(
	const struct swapz_zswap_import_decoder_lease *lease,
	const struct swapz_original_decode_record *record, swapz_u32 ceiling,
	const swapz_u8 *input, swapz_u32 input_capacity,
	swapz_u8 *scratch, swapz_u32 scratch_capacity,
	swapz_u8 *output, swapz_u32 output_capacity)
{
	swapz_u8 digest[32];
	swapz_u8 difference = 0U;
	unsigned int offset;
	int result;

	if (!lease || !record || !input || !scratch || !output)
		return -EINVAL;
	if (!lease->owner)
		return -ESTALE;
	if (record->representation != SWAPZ_ZSWAP_IMPORT_REPRESENTATION ||
	    (record->codec != SWAPZ_ZSWAP_IMPORT_LZ4_CODEC &&
	     record->codec != SWAPZ_ZSWAP_IMPORT_LZO1X_CODEC) ||
	    record->version != SWAPZ_ZSWAP_IMPORT_VERSION ||
	    record->dictionary_id != 0U)
		return -EOPNOTSUPP;
	if (lease->codec != record->codec || lease->version != record->version)
		return -ESTALE;
	if (!swapz_original_decode_length_valid(ceiling, record->compressed_length) ||
	    record->decoded_length != SWAPZ_BLOCK_BYTES ||
	    input_capacity < record->compressed_length ||
	    scratch_capacity != SWAPZ_BLOCK_BYTES || output_capacity != SWAPZ_BLOCK_BYTES)
		return -EMSGSIZE;
	if (!swapz_original_decode_disjoint(lease, record, input, scratch, output))
		return -EINVAL;
	if (swapz_crc32c_bytes(input, record->compressed_length) != record->compressed_crc32c)
		return -EBADMSG;
	if (record->codec == SWAPZ_ZSWAP_IMPORT_LZO1X_CODEC) {
#if !defined(SWAPZ_ZSWAP_IMPORT_HOST_TEST) || defined(SWAPZ_ZSWAP_IMPORT_ORIGINAL_LZO_HOST_TEST)
		size_t decoded_length = SWAPZ_BLOCK_BYTES;

		result = lzo1x_decompress_safe(input, record->compressed_length,
			scratch, &decoded_length);
		if (result != LZO_E_OK)
			return -EBADMSG;
		if (decoded_length != SWAPZ_BLOCK_BYTES)
			return -EMSGSIZE;
#else
		return -EOPNOTSUPP;
#endif
	} else {
		result = LZ4_decompress_safe((const char *)input, (char *)scratch,
			(int)record->compressed_length, (int)SWAPZ_BLOCK_BYTES);
		if (result < 0)
			return -EBADMSG;
		if (result != (int)SWAPZ_BLOCK_BYTES)
			return -EMSGSIZE;
	}
	if (swapz_zswap_import_sha256(scratch, digest))
		return -EIO;
	for (offset = 0U; offset < sizeof(digest); ++offset)
		difference |= digest[offset] ^ record->original_sha256[offset];
	if (difference)
		return -EBADMSG;
	/* Commit only after every guard. memmove also has defined behavior for
	 * the intentional overlap-guard mutant in the rootless test. */
	memmove(output, scratch, SWAPZ_BLOCK_BYTES);
	return 0;
}
