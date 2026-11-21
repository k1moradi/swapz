// SPDX-License-Identifier: GPL-2.0-only
/* Round052 rootless codec-only evidence. No source slot, DM lease or I/O. */
#include "codec.h"
#include <errno.h>
#include <limits.h>
#include <lz4.h>
#include <lz4frame.h>
#include <openssl/sha.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

typedef unsigned char u8;
static unsigned int assertions;
#define CHECK(condition) do { \
    ++assertions; \
    if (!(condition)) { \
        fprintf(stderr, "ROUND052_CODEC_FIRST_ERROR line=%d assertion=%s\n", \
                __LINE__, #condition); \
        return 1; \
    } \
} while (0)

/* The extracted pinned original crypto/lz4.c wrapper takes a kernel workmem
 * argument. liblz4 here only supplies the HOST RAW LZ4 block implementation:
 * this is NOT execution of the pinned kernel's implementation or a live pool. */
static int kernel_lz4_compress_default(const u8 *source, u8 *destination,
                                      unsigned int source_length,
                                      unsigned int destination_capacity,
                                      void *kernel_workmem)
{
    (void)kernel_workmem;
    if (source_length > (unsigned int)INT_MAX ||
        destination_capacity > (unsigned int)INT_MAX)
        return 0;
    return LZ4_compress_default((const char *)source, (char *)destination,
                                (int)source_length, (int)destination_capacity);
}
/* The pinned original crypto/lz4.c assigns its positive signed LZ4 result
 * to an unsigned length without a cast. Keep its extracted bytes unchanged;
 * isolate only this genuine upstream signedness diagnostic from the host
 * build. Our product/fixture remains -Wconversion -Werror throughout. */
#if defined(__clang__)
#pragma clang diagnostic push
#pragma clang diagnostic ignored "-Wsign-conversion"
#elif defined(__GNUC__)
#pragma GCC diagnostic push
#pragma GCC diagnostic ignored "-Wsign-conversion"
#endif
#define LZ4_compress_default kernel_lz4_compress_default
#include "round052-original-crypto-lz4-extracted.inc"
#undef LZ4_compress_default
#if defined(__clang__)
#pragma clang diagnostic pop
#elif defined(__GNUC__)
#pragma GCC diagnostic pop
#endif

/* Hypothetical separately tagged lower-stage admission, NEVER normal RAW.
 * A source-supplied full original page is mandatory for the rejection path.
 * Producer provenance is deliberately HOST-only, not original MM AUTH. */
enum host_source_kind {
    HOST_RAW_BLOCK,
    HOST_LZ4_FRAME,
    HOST_LZ4_DICTIONARY,
    HOST_LZO,
    HOST_ZSTD,
    HOST_UNKNOWN
};
static int verify_host_lower_candidate(const u8 *compressed,
                                       unsigned int compressed_length,
                                       enum host_source_kind source_kind,
                                       swapz_u8 encoding,
                                       swapz_u32 expected_crc32c,
                                       const u8 expected_sha256[SHA256_DIGEST_LENGTH],
                                       const u8 original_page[SWAPZ_BLOCK_BYTES],
                                       u8 result_page[SWAPZ_BLOCK_BYTES])
{
    u8 candidate[SWAPZ_BLOCK_BYTES];
    u8 digest[SHA256_DIGEST_LENGTH];
    int decoded_length;
    /* Normal upper RAW fallback is always exactly the ORIGINAL full page. */
    memcpy(result_page, original_page, SWAPZ_BLOCK_BYTES);
    if (!compressed || source_kind != HOST_RAW_BLOCK ||
        encoding != SWAPZ_ENCODING_LZ4 || !compressed_length ||
        compressed_length > SWAPZ_MAX_COMPRESSED ||
        swapz_crc32c_bytes(compressed, compressed_length) != expected_crc32c)
        return 0;
    decoded_length = LZ4_decompress_safe((const char *)compressed,
                                         (char *)candidate,
                                         (int)compressed_length,
                                         (int)SWAPZ_BLOCK_BYTES);
    if (decoded_length != (int)SWAPZ_BLOCK_BYTES ||
        !SHA256(candidate, SWAPZ_BLOCK_BYTES, digest) ||
        memcmp(digest, expected_sha256, sizeof(digest)) ||
        memcmp(candidate, original_page, SWAPZ_BLOCK_BYTES))
        return 0;
    memcpy(result_page, candidate, SWAPZ_BLOCK_BYTES);
    return 1; /* HOST subset only, no permissions or map/ACK. */
}

static int target_relative_page_valid(uint64_t sector, uint64_t target_sectors)
{
    const uint64_t page_sectors = SWAPZ_BLOCK_BYTES / 512U;
    return target_sectors >= page_sectors &&
           sector % page_sectors == 0 &&
           sector <= target_sectors - page_sectors;
}

static void make_original_page(u8 page[SWAPZ_BLOCK_BYTES], unsigned int seed)
{
    uint32_t state = seed + UINT32_C(0x9e3779b9);
    unsigned int index;
    for (index = 0; index < SWAPZ_BLOCK_BYTES; ++index) {
        state ^= state << 13;
        state ^= state >> 17;
        state ^= state << 5;
        switch (seed % 8U) {
        case 0: page[index] = 0; break;
        case 1: page[index] = (u8)(seed & 0xffU); break;
        case 2: page[index] = (u8)(index % 3U); break;
        case 3: page[index] = (u8)(index >= 4032U ? index : 0U); break;
        case 4: page[index] = (u8)(index % 64U == 0U ? state : 0U); break;
        case 5: page[index] = (u8)(index % 2U ? 0xffU : 0); break;
        case 6: page[index] = (u8)state; break;
        default: page[index] = (u8)(state & 0x1fU); break;
        }
    }
}

static int test_page(unsigned int seed)
{
    u8 original[SWAPZ_BLOCK_BYTES];
    u8 compressed[LZ4_COMPRESSBOUND(SWAPZ_BLOCK_BYTES)];
    u8 result[SWAPZ_BLOCK_BYTES];
    u8 sha[SHA256_DIGEST_LENGTH];
    u8 corrupted_sha[SHA256_DIGEST_LENGTH];
    /* Original mm/zswap.c supplies dlen=PAGE_SIZE, not LZ4_COMPRESSBOUND. */
    unsigned int length = SWAPZ_BLOCK_BYTES;
    swapz_u32 crc;
    int rc;
    make_original_page(original, seed);
    CHECK(SHA256(original, sizeof(original), sha) != NULL);
    if (__lz4_compress_crypto(original, SWAPZ_BLOCK_BYTES, compressed,
                              &length, NULL) != 0) {
        /* Original kernel would not retain these invalid compressed bytes.
         * Incompressible source must remain full original 4096 RAW. */
        CHECK(verify_host_lower_candidate(NULL, 0U, HOST_RAW_BLOCK,
                                          SWAPZ_ENCODING_LZ4, 0U, sha,
                                          original, result) == 0);
        CHECK(memcmp(result, original, sizeof(original)) == 0);
        return 0;
    }
    crc = swapz_crc32c_bytes(compressed, length);
    rc = verify_host_lower_candidate(compressed, length, HOST_RAW_BLOCK,
                                     SWAPZ_ENCODING_LZ4, crc, sha, original,
                                     result);
    CHECK(rc == (length <= SWAPZ_MAX_COMPRESSED ? 1 : 0));
    CHECK(memcmp(result, original, sizeof(original)) == 0);
    CHECK(verify_host_lower_candidate(compressed, length, HOST_ZSTD,
                                      SWAPZ_ENCODING_LZ4, crc, sha,
                                      original, result) == 0);
    CHECK(memcmp(result, original, sizeof(original)) == 0);
    CHECK(verify_host_lower_candidate(compressed, length, HOST_LZO,
                                      SWAPZ_ENCODING_LZ4, crc, sha,
                                      original, result) == 0);
    CHECK(verify_host_lower_candidate(compressed, length, HOST_UNKNOWN,
                                      SWAPZ_ENCODING_LZ4, crc, sha,
                                      original, result) == 0);
    CHECK(verify_host_lower_candidate(compressed, length, HOST_LZ4_FRAME,
                                      SWAPZ_ENCODING_LZ4, crc, sha,
                                      original, result) == 0);
    CHECK(verify_host_lower_candidate(compressed, length, HOST_LZ4_DICTIONARY,
                                      SWAPZ_ENCODING_LZ4, crc, sha,
                                      original, result) == 0);
    CHECK(verify_host_lower_candidate(compressed, length, HOST_RAW_BLOCK,
                                      SWAPZ_ENCODING_DELTA64, crc, sha,
                                      original, result) == 0);
    CHECK(verify_host_lower_candidate(compressed, length, HOST_RAW_BLOCK,
                                      SWAPZ_ENCODING_DELTA64_SHUF8, crc, sha,
                                      original, result) == 0);
    CHECK(verify_host_lower_candidate(compressed, length, HOST_RAW_BLOCK,
                                      SWAPZ_ENCODING_LZ4, crc ^ 1U, sha,
                                      original, result) == 0);
    memcpy(corrupted_sha, sha, sizeof(sha));
    corrupted_sha[31] ^= 1U;
    CHECK(verify_host_lower_candidate(compressed, length, HOST_RAW_BLOCK,
                                      SWAPZ_ENCODING_LZ4, crc, corrupted_sha,
                                      original, result) == 0);
    CHECK(memcmp(result, original, sizeof(original)) == 0);
    if (seed == 0U) {
        u8 framed[LZ4F_HEADER_SIZE_MAX + LZ4_COMPRESSBOUND(SWAPZ_BLOCK_BYTES) + 32U];
        const size_t framed_length = LZ4F_compressFrame(framed, sizeof(framed),
                                                         original, sizeof(original), NULL);
        CHECK(!LZ4F_isError(framed_length));
        CHECK(verify_host_lower_candidate(framed, (unsigned int)framed_length,
                                          HOST_RAW_BLOCK, SWAPZ_ENCODING_LZ4,
                                          swapz_crc32c_bytes(framed, (swapz_u32)framed_length),
                                          sha, original, result) == 0);
        CHECK(memcmp(result, original, sizeof(original)) == 0);
    }
    if (length <= SWAPZ_MAX_COMPRESSED) {
        const u8 prior = compressed[length - 1U];
        compressed[length - 1U] ^= 0x80U;
        CHECK(verify_host_lower_candidate(compressed, length, HOST_RAW_BLOCK,
                                          SWAPZ_ENCODING_LZ4, crc, sha,
                                          original, result) == 0);
        CHECK(memcmp(result, original, sizeof(original)) == 0);
        compressed[length - 1U] = prior;
    }
    return 0;
}

static int test_product_ram_extent(void)
{
    u8 compressed[SWAPZ_MAX_COMPRESSED + 1U];
    u8 lower[4U * SWAPZ_BLOCK_BYTES];
    u8 protected_header[SWAPZ_BLOCK_BYTES];
    u8 original_header[SWAPZ_BLOCK_BYTES];
    struct swapz_ram_extent extent;
    struct swapz_decoded records[1];
    const u8 *payload = NULL;
    unsigned int size_index;
    unsigned int extent_index;
    static const swapz_u16 sizes[] = {0, 1, 3568, 3569, 4095, 4096};
    static const swapz_u32 extents[] = {4096, 8192, 16384};
    memset(compressed, 0x43, sizeof(compressed));
    memset(protected_header, 0xa7, sizeof(protected_header));
    memcpy(original_header, protected_header, sizeof(original_header));
    CHECK(swapz_crc32c_bytes("123456789", 9U) == UINT32_C(0xe3069283));
    CHECK(swapz_ram_extent_begin(&extent, lower, 12288U, 1U, records, 1U) == -EINVAL);
    CHECK(swapz_ram_extent_begin(&extent, lower, 4096U, 1U, records, 1U) == 0);
    CHECK(swapz_ram_extent_seal(&extent) == -EINVAL);
    /* Isolate the count guard from later cursor and length guards. */
    extent.payload_start = 4095U;
    extent.last_record.payload_offset = 4095U;
    extent.last_record.payload_length = 1U;
    CHECK(swapz_ram_extent_seal(&extent) == -EINVAL);
    for (extent_index = 0; extent_index < 3U; ++extent_index) {
        for (size_index = 0; size_index < sizeof(sizes) / sizeof(sizes[0]); ++size_index) {
            const swapz_u16 length = sizes[size_index];
            swapz_u32 offset;
            swapz_u32 index;
            int result;
            memset(lower, 0x7c, sizeof(lower));
            CHECK(swapz_ram_extent_begin(&extent, lower, extents[extent_index],
                                         1U, records, 1U) == 0);
            result = swapz_ram_extent_append(&extent, 7U, 2U,
                                             compressed, length,
                                             SWAPZ_ENCODING_LZ4);
            if (!length || length > SWAPZ_MAX_COMPRESSED) {
                CHECK(result == -EINVAL);
                continue;
            }
            CHECK(result == 0);
            CHECK(swapz_ram_extent_seal(&extent) == 0);
            offset = extents[extent_index] - length;
            for (index = 0; index < offset; ++index)
                CHECK(lower[index] == 0U);
            CHECK(memcmp(lower + offset, compressed, length) == 0);
            CHECK(swapz_ram_extent_read(&extent, 0U, 7U, 2U, &payload) == 0);
            CHECK(payload == lower + offset);
            CHECK(swapz_ram_extent_read(&extent, 0U, 7U, 3U, &payload) == -EUCLEAN);
            lower[offset] ^= 1U;
            CHECK(swapz_ram_extent_read(&extent, 0U, 7U, 2U, &payload) == -EBADMSG);
            lower[offset] ^= 1U;
            CHECK(swapz_ram_extent_read(&extent, 0U, 7U, 2U, &payload) == 0);
            records[0].encoding = SWAPZ_ENCODING_INVALID;
            CHECK(swapz_ram_extent_read(&extent, 0U, 7U, 2U, &payload) == -EUCLEAN);
            records[0].encoding = SWAPZ_ENCODING_LZ4;
            records[0].generation = 0U;
            CHECK(swapz_ram_extent_read(&extent, 0U, 7U, 0U, &payload) == -EUCLEAN);
            records[0].generation = 2U;
            if (length == 3568U) {
                /* Keep every other range and CRC guard valid so this is an
                 * isolated, nonvacuous >3568 read-boundary mutation. */
                records[0].payload_offset = (swapz_u16)(offset - 1U);
                extent.payload_start = (swapz_u16)(offset - 1U);
                records[0].payload_length = 3569U;
                records[0].payload_crc32c =
                    swapz_crc32c_bytes(lower + offset - 1U, 3569U);
                CHECK(swapz_ram_extent_read(&extent, 0U, 7U, 2U, &payload) == -EUCLEAN);
                records[0].payload_offset = (swapz_u16)offset;
                extent.payload_start = (swapz_u16)offset;
                records[0].payload_length = length;
                records[0].payload_crc32c = swapz_crc32c_bytes(lower + offset, length);
            }
            if (offset > 0U) {
                records[0].payload_offset = (swapz_u16)(offset - 1U);
                records[0].payload_crc32c = swapz_crc32c_bytes(lower + offset - 1U, length);
                CHECK(swapz_ram_extent_read(&extent, 0U, 7U, 2U, &payload) == -EUCLEAN);
                records[0].payload_offset = (swapz_u16)offset;
                records[0].payload_crc32c = swapz_crc32c_bytes(lower + offset, length);
            }
            CHECK(swapz_ram_extent_read(&extent, 0U, 7U, 2U, &payload) == 0);
        }
    }
    CHECK(swapz_ram_extent_begin(&extent, lower, 4096U, 1U, records, 1U) == 0);
    CHECK(swapz_ram_extent_append(&extent, 7U, 2U, compressed, 32U,
                                   SWAPZ_ENCODING_LZ4) == 0);
    CHECK(swapz_ram_extent_append(&extent, 8U, 2U, compressed, 32U,
                                   SWAPZ_ENCODING_LZ4) == -ENOSPC);
    CHECK(swapz_ram_extent_begin(&extent, lower, 4096U, 1U, records, 1U) == 0);
    CHECK(swapz_ram_extent_append(&extent, 7U, 2U, compressed, 32U,
                                   SWAPZ_ENCODING_INVALID) == -EINVAL);
    CHECK(target_relative_page_valid(0U, 8U));
    CHECK(target_relative_page_valid(8U, 16U));
    CHECK(!target_relative_page_valid(1U, 16U));
    CHECK(!target_relative_page_valid(8U, 8U));
    CHECK(!target_relative_page_valid(UINT64_MAX, UINT64_MAX));
    CHECK(!target_relative_page_valid(8U, 7U));
    CHECK(memcmp(protected_header, original_header, sizeof(protected_header)) == 0);
    return 0;
}

/* Host-only legacy RAM descriptor width boundaries. These test the real
 * codec's earliest refusal and verify no rejected snapshot can touch scratch.
 * They do not load a module or write a SWAPSPACE2 header. */
static int test_legacy_metadata_lengths(void)
{
    u8 scratch[SWAPZ_BLOCK_BYTES];
    struct swapz_ram_extent_metadata snapshot = { 0 };
    struct swapz_header malformed_header = { 0 };
    unsigned int index;

    memset(scratch, 0xa5, sizeof(scratch));
    /* 65535 must not narrow to a valid RAM descriptor length. */
    snapshot.length = UINT16_MAX;
    CHECK(swapz_attach_extent_metadata(scratch, SWAPZ_BLOCK_BYTES,
                                       &snapshot) == -EINVAL);
    /* Maximal u8 record_count yields exactly 4096 bytes rather than a
     * wrapping 16-bit descriptor length. It cannot match a 16-byte snapshot. */
    snapshot.length = (swapz_u16)sizeof(struct swapz_header);
    snapshot.bytes[offsetof(struct swapz_header, record_count)] = UINT8_MAX;
    CHECK(swapz_attach_extent_metadata(scratch, SWAPZ_BLOCK_BYTES,
                                       &snapshot) == -EUCLEAN);
    for (index = 0; index < SWAPZ_BLOCK_BYTES; ++index)
        CHECK(scratch[index] == 0xa5U);

    memset(scratch, 0, sizeof(scratch));
    malformed_header.magic_le = SWAPZ_MAGIC;
    malformed_header.extent_blocks = 1U;
    malformed_header.record_count = UINT8_MAX;
    malformed_header.sequence_le = 1U;
    memcpy(scratch, &malformed_header, sizeof(malformed_header));
    CHECK(swapz_validate_metadata_crc(scratch, SWAPZ_BLOCK_BYTES) == -EUCLEAN);
    return 0;
}

int main(void)
{
    unsigned int seed;
    CHECK(SWAPZ_CODEC_METADATA_ON_MEDIA == 0U);
    CHECK(SWAPZ_MAX_COMPRESSED == 3568U);
    CHECK(SWAPZ_ENCODING_LZ4 == 0U);
    CHECK(SWAPZ_ENCODING_DELTA64 == 1U);
    CHECK(SWAPZ_ENCODING_DELTA64_SHUF8 == 2U);
    CHECK(test_product_ram_extent() == 0);
    CHECK(test_legacy_metadata_lengths() == 0);
    for (seed = 0; seed < 96U; ++seed)
        CHECK(test_page(seed) == 0);
    printf("ROUND052_HOST_RAW_LZ4_SUBSET_PASS seed_cases=96 assertions=%u "
           "source_authenticated=0 physical_io=0\n", assertions);
    return 0;
}
