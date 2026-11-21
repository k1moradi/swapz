// SPDX-License-Identifier: GPL-2.0-only
/*
 * Round056 SOURCE-ONLY host contract, never included by production Kbuild.
 * Original Linux's pinned crypto/lzo.c wrapper and lib/lzo implementations
 * are compiled into this fixture by the driver. No zswap pool, module, map,
 * source slot, or physical target is owned or authenticated here.
 */
#include "codec.h"
#include <errno.h>
#include <limits.h>
#include <lz4.h>
#include <openssl/sha.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <linux/lzo.h>

typedef uint8_t u8;

/* The following include is generated verbatim from two functions in the
 * pinned ORIGINAL crypto/lzo.c. Its u32 dlen assignment is a documented
 * upstream Linux size_t->unsigned-int ABI conversion; the exact extracted
 * original functions alone have the narrow diagnostic exception. */
#pragma GCC diagnostic push
#pragma GCC diagnostic ignored "-Wconversion"
#include "round056-original-crypto-lzo-wrapper.inc"
#pragma GCC diagnostic pop

#define CHECK(condition) do { \
    if (!(condition)) { \
        fprintf(stderr, "ROUND056_CODEC_FIRST_ERROR line=%d\n", __LINE__); \
        return 1; \
    } \
} while (0)

#define PROFILE_LZ4_V1 1U
#define PROFILE_LZO1X_V0 2U
#define PROFILE_VERSION 1U

struct profile_record {
    uint32_t codec;
    uint32_t selected_driver; /* Test evidence, NOT original provenance. */
    uint32_t format_version;
    uint32_t dictionary_id;
    uint32_t compressed_length;
    uint32_t decoded_length;
    uint32_t compressed_crc32c;
    uint8_t full_original_sha256[SHA256_DIGEST_LENGTH];
};

/* Exactly 60 test-only bytes, not part of the normal 20-byte swapz map. */
_Static_assert(sizeof(struct profile_record) == 60U,
               "unexpected host profile descriptor allocation size");

static int ranges_overlap(const void *first, size_t first_length,
                          const void *second, size_t second_length)
{
    const uintptr_t first_address = (uintptr_t)first;
    const uintptr_t second_address = (uintptr_t)second;
    if (first_address >= second_address)
        return first_address - second_address < second_length;
    return second_address - first_address < first_length;
}

/* All scratch/output buffers are caller-owned and exclusive; no allocation.
 * Never expose even one output byte until payload CRC, decompressed extent
 * length, decoder return status, and ORIGINAL full-page SHA have succeeded.
 * The selected upstream implementation must be verified by a separate real
 * original-source owner before this test-only profile becomes admissible.
 * Do not cache zswap pool IDs, pointers, transform objects or dictionaries. */
static int round056_decode_profile(const struct profile_record *record,
                                   const uint8_t *compressed,
                                   size_t available_compressed,
                                   uint8_t *scratch, size_t scratch_capacity,
                                   uint8_t *output, size_t output_capacity)
{
    uint8_t actual_sha256[SHA256_DIGEST_LENGTH];
    size_t decoded_bytes = SWAPZ_BLOCK_BYTES;
    int result;

    if (!record || !compressed || !scratch || !output)
        return -EINVAL;
    if (record->codec != PROFILE_LZ4_V1 &&
        record->codec != PROFILE_LZO1X_V0)
        return -EOPNOTSUPP;
    if (record->selected_driver != record->codec ||
        record->format_version != PROFILE_VERSION ||
        record->dictionary_id != 0U)
        return -EOPNOTSUPP;
    if (!record->compressed_length ||
        record->compressed_length > SWAPZ_MAX_COMPRESSED ||
        record->compressed_length > available_compressed ||
        record->decoded_length != SWAPZ_BLOCK_BYTES ||
        scratch_capacity != SWAPZ_BLOCK_BYTES ||
        output_capacity != SWAPZ_BLOCK_BYTES)
        return -EMSGSIZE;
    if (ranges_overlap(scratch, scratch_capacity, output, output_capacity) ||
        ranges_overlap(scratch, scratch_capacity, compressed, record->compressed_length) ||
        ranges_overlap(output, output_capacity, compressed, record->compressed_length))
        return -EINVAL;
    if (swapz_crc32c_bytes(compressed, record->compressed_length) !=
        record->compressed_crc32c)
        return -EBADMSG;

    if (record->codec == PROFILE_LZO1X_V0) {
        /* Original Linux lib/lzo/lzo1x_decompress_safe.c reports trailing
         * input with LZO_E_INPUT_NOT_CONSUMED, which MUST be rejected. */
        unsigned int lzo_decoded_bytes = SWAPZ_BLOCK_BYTES;
        result = __lzo_decompress(compressed, record->compressed_length,
                                  scratch, &lzo_decoded_bytes);
        if (result != 0)
            return -EBADMSG;
        decoded_bytes = lzo_decoded_bytes;
    } else {
        result = LZ4_decompress_safe((const char *)compressed, (char *)scratch,
                                     (int)record->compressed_length,
                                     (int)SWAPZ_BLOCK_BYTES);
        if (result < 0)
            return -EBADMSG;
        decoded_bytes = (size_t)result;
    }
    if (decoded_bytes != SWAPZ_BLOCK_BYTES)
        return -EBADMSG;
    if (!SHA256(scratch, SWAPZ_BLOCK_BYTES, actual_sha256))
        return -EIO;
    if (memcmp(actual_sha256, record->full_original_sha256,
               sizeof(actual_sha256)) != 0)
        return -EBADMSG;
    memcpy(output, scratch, SWAPZ_BLOCK_BYTES);
    return 0;
}

static void fill_page(uint8_t *page, unsigned int seed)
{
    size_t offset;
    uint32_t random_state = 0x9e3779b9U ^ seed;
    for (offset = 0; offset < SWAPZ_BLOCK_BYTES; ++offset) {
        random_state = random_state * 1664525U + 1013904223U;
        switch (seed % 7U) {
        case 0U: page[offset] = 0U; break;
        case 1U: page[offset] = 0x7fU; break;
        case 2U: page[offset] = (uint8_t)((offset / 128U + seed) & 0x0fU); break;
        case 3U: page[offset] = (uint8_t)(offset % 4U == 0U ? seed : 0U); break;
        case 4U: page[offset] = (uint8_t)(random_state >> 24U); break;
        case 5U: page[offset] = (uint8_t)((offset / 32U) ^ seed); break;
        default: page[offset] = (uint8_t)((offset + seed) % 11U); break;
        }
    }
}

static void prepare_record(struct profile_record *record,
                           const uint8_t *original, const uint8_t *compressed,
                           unsigned int compressed_length, uint32_t codec)
{
    *record = (struct profile_record){
        .codec = codec,
        .selected_driver = codec,
        .format_version = PROFILE_VERSION,
        .dictionary_id = 0,
        .compressed_length = compressed_length,
        .decoded_length = SWAPZ_BLOCK_BYTES,
        .compressed_crc32c = swapz_crc32c_bytes(compressed, compressed_length)
    };
    (void)SHA256(original, SWAPZ_BLOCK_BYTES, record->full_original_sha256);
}

static int output_is_sentinel(const uint8_t *output)
{
    size_t offset;
    for (offset = 0; offset < SWAPZ_BLOCK_BYTES; ++offset)
        if (output[offset] != 0xa5U)
            return 0;
    return 1;
}

int main(void)
{
    uint8_t original[SWAPZ_BLOCK_BYTES];
    uint8_t compressed[SWAPZ_BLOCK_BYTES * 2U];
    uint8_t scratch[SWAPZ_BLOCK_BYTES];
    uint8_t output[SWAPZ_BLOCK_BYTES];
    _Alignas(unsigned short) uint8_t compression_workspace[LZO1X_1_MEM_COMPRESS];
    struct profile_record record;
    unsigned int accepted_lzo = 0;
    unsigned int accepted_lz4 = 0;
    unsigned int seed;

    CHECK(SWAPZ_CODEC_METADATA_ON_MEDIA == 0U);
    CHECK(SWAPZ_MAX_COMPRESSED == 3568U);
    for (seed = 0; seed < 49U; ++seed) {
        unsigned int compressed_length = (unsigned int)sizeof(compressed);
        int lz4_length;

        fill_page(original, seed);
        CHECK(__lzo_compress(original, SWAPZ_BLOCK_BYTES, compressed,
                             &compressed_length, compression_workspace) == 0);
        if (compressed_length <= SWAPZ_MAX_COMPRESSED) {
            ++accepted_lzo;
            prepare_record(&record, original, compressed, compressed_length,
                           PROFILE_LZO1X_V0);
            memset(compression_workspace, 0x5c, sizeof(compression_workspace));
            memset(output, 0xa5, sizeof(output));
            CHECK(round056_decode_profile(&record, compressed,
                  sizeof(compressed), scratch, sizeof(scratch),
                  output, sizeof(output)) == 0);
            CHECK(memcmp(original, output, sizeof(original)) == 0);

            /* Corrupt only the expected full original identity; the
             * compressed CRC remains correct. No output may escape. */
            record.full_original_sha256[0] ^= 1U;
            memset(output, 0xa5, sizeof(output));
            CHECK(round056_decode_profile(&record, compressed,
                  sizeof(compressed), scratch, sizeof(scratch),
                  output, sizeof(output)) == -EBADMSG);
            CHECK(output_is_sentinel(output));
            record.full_original_sha256[0] ^= 1U;

            record.compressed_crc32c ^= 1U;
            CHECK(round056_decode_profile(&record, compressed,
                  sizeof(compressed), scratch, sizeof(scratch),
                  output, sizeof(output)) == -EBADMSG);
            CHECK(output_is_sentinel(output));
            record.compressed_crc32c ^= 1U;

            record.codec = 0xffU;
            CHECK(round056_decode_profile(&record, compressed,
                  sizeof(compressed), scratch, sizeof(scratch),
                  output, sizeof(output)) == -EOPNOTSUPP);
            record.codec = PROFILE_LZO1X_V0;
            record.dictionary_id = 1U;
            CHECK(round056_decode_profile(&record, compressed,
                  sizeof(compressed), scratch, sizeof(scratch),
                  output, sizeof(output)) == -EOPNOTSUPP);
            record.dictionary_id = 0U;
            record.format_version = 2U;
            CHECK(round056_decode_profile(&record, compressed,
                  sizeof(compressed), scratch, sizeof(scratch),
                  output, sizeof(output)) == -EOPNOTSUPP);
            record.format_version = PROFILE_VERSION;

            record.compressed_length = SWAPZ_MAX_COMPRESSED + 1U;
            CHECK(round056_decode_profile(&record, compressed,
                  sizeof(compressed), scratch, sizeof(scratch),
                  output, sizeof(output)) == -EMSGSIZE);
            record.compressed_length = compressed_length;

            /* The exact ORIGINAL LZO decoder must flag the extra byte
             * as INPUT_NOT_CONSUMED rather than silently accepting it. */
            if (compressed_length < SWAPZ_MAX_COMPRESSED) {
                compressed[compressed_length] = 0x8eU;
                record.compressed_length = compressed_length + 1U;
                record.compressed_crc32c =
                    swapz_crc32c_bytes(compressed, record.compressed_length);
                CHECK(round056_decode_profile(&record, compressed,
                      sizeof(compressed), scratch, sizeof(scratch),
                      output, sizeof(output)) == -EBADMSG);
                CHECK(output_is_sentinel(output));
            }
        }

        lz4_length = LZ4_compress_default((const char *)original,
                                         (char *)compressed,
                                         SWAPZ_BLOCK_BYTES,
                                         (int)sizeof(compressed));
        CHECK(lz4_length > 0);
        if (lz4_length <= (int)SWAPZ_MAX_COMPRESSED) {
            ++accepted_lz4;
            prepare_record(&record, original, compressed,
                           (unsigned int)lz4_length, PROFILE_LZ4_V1);
            memset(output, 0xa5, sizeof(output));
            CHECK(round056_decode_profile(&record, compressed,
                  sizeof(compressed), scratch, sizeof(scratch),
                  output, sizeof(output)) == 0);
            CHECK(memcmp(original, output, sizeof(original)) == 0);
        }
    }
    CHECK(accepted_lzo >= 20U);
    CHECK(accepted_lz4 >= 20U);
    printf("ROUND056_ORIGINAL_LZO1X_AND_RAW_LZ4_HOST_PROFILE_PASS "
           "lzo_pages=%u lz4_pages=%u profile_bytes=%zu "
           "decode_scratch=4096 output_scratch=4096 compressor_workspace=%zu "
           "source_authenticated=0 physical_io=0\n",
           accepted_lzo, accepted_lz4, sizeof(record),
           sizeof(compression_workspace));
    return 0;
}
