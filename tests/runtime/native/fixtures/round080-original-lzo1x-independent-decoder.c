/* SPDX-License-Identifier: GPL-2.0-only */
/*
 * Round080 Agent7 genuine original Linux LZO1X byte stream, HOST ONLY.
 *
 * Compiled with exact pinned torvalds/linux lib/lzo/lzo1x_compress.c and
 * lib/lzo/lzo1x_decompress_safe.c plus read-only product decoder owner/codec.
 * Host side provenance and lower completion bits are NOT real selected Linux
 * STORED source/DM authentication, physical FUA or actual bio_endio.
 */
#include <errno.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <openssl/sha.h>
#include <linux/lzo.h>

#define SOURCE_MAPPED_AUTHENTICATED 0
#define DIRECT_COMPRESSED_HANDOFF 0
#define FORCED_RAW_BYPASS 0
#define SWAPZ_ZSWAP_IMPORT_HOST_TEST 1
#define SWAPZ_ZSWAP_IMPORT_ORIGINAL_LZO_HOST_TEST 1
#define SWAPZ_ZSWAP_IMPORT_DECODER_HOST_TEST 1
#include "../../../../src/kernel/zswap-import-decoder-owner.h"
#include "../../../../src/kernel/zswap-direct-handoff.h"
#include "../../../../src/kernel/authority.h"

_Static_assert(SWAPZ_ZSWAP_IMPORT_LZO1X_CODEC == 2U, "original LZO=2");
_Static_assert(SWAPZ_DIRECT_ZSWAP_ZSTD == 2, "independent direct ZSTD=2");
_Static_assert(SWAPZ_ZSWAP_IMPORT_ACTIVE == 0U, "import inactive");
_Static_assert(SWAPZ_DIRECT_HANDOFF_PRODUCTION_ENABLED == 0U, "direct inactive");
_Static_assert(SWAPZ_CODEC_METADATA_ON_MEDIA == 0U, "no disk metadata");
_Static_assert(SWAPZ_MAX_COMPRESSED == 3568U, "dormant import cap");
_Static_assert(SWAPZ_LINUX_SWAP_HEADER_BLOCKS == 1U, "protected first 4096");
_Static_assert(sizeof(struct swapz_map) == 20U, "volatile 20B map");
_Static_assert(SOURCE_MAPPED_AUTHENTICATED == 0, "AUTH0");
_Static_assert(DIRECT_COMPRESSED_HANDOFF == 0, "direct off");
_Static_assert(FORCED_RAW_BYPASS == 0, "forced RAW off");

enum { ORIGINAL_LENGTH = SWAPZ_BLOCK_BYTES, LZO_OUTPUT_CAPACITY = 5000U };
enum original_representation { ORIGINAL_COMPRESSED_LZO, FULL_UNCOMPRESSED_RAW };

struct host_source_witness {
    bool genuine_original_namespace;
    bool original_selected_source_verified; /* Host ASSERTION ONLY, not AUTH. */
    bool immutable_owned_copy;
    bool original_eviction;
    bool decoder_is_retained;
    bool retired_original_decoder;
    bool no_recompression;
    bool no_secondary_reclaim;
    enum original_representation representation;
    uint8_t original_codec;
    uint8_t original_version;
    uint8_t swapz_disk_encoding;
    uint64_t logical_page;
    uint64_t generation;
    uint64_t stored_identity;
    uint64_t store_generation;
    uint64_t gc_epoch;
    uint32_t compressed_bytes;
    uint32_t source_capacity;
    uint32_t lower_actual_bytes;
    uint8_t independent_sha256[SHA256_DIGEST_LENGTH];
};

static uint8_t original_page[ORIGINAL_LENGTH];
static uint8_t real_original_lzo[LZO_OUTPUT_CAPACITY];
static uint8_t scratch_page[ORIGINAL_LENGTH];
static uint8_t output_page[ORIGINAL_LENGTH];
static uint8_t original_digest[SHA256_DIGEST_LENGTH];
static unsigned short compressor_workspace[8192U];
static uint32_t checks;
static uint32_t synthetic_upper_acks;

#define EXPECT(condition) do { \
    ++checks; \
    if (!(condition)) { \
        fprintf(stderr, "FIRST_ERROR line=%d check=%s\n", __LINE__, #condition); \
        return 1; \
    } \
} while (0)
#define EXPECT_STATUS(actual, expected) EXPECT((actual) == (expected))

/*
 * Explicitly preflight test-only model source provenance. A C mutant of each
 * gate is executed against the relevant negative before any product decode.
 * The independent original Linux stored-entry lock is NOT present here.
 */
static int guarded_product_lzo_read(
    const struct host_source_witness *source,
    const struct swapz_zswap_import_decoder_lease *lease,
    const struct swapz_zswap_import_record *record,
    const struct swapz_zswap_import_read_authority *authority,
    const uint8_t *compressed, uint32_t readable_capacity,
    uint8_t *scratch, uint8_t *output, uint32_t *host_ack_count)
{
    int result;
    if (!source || !lease || !record || !authority || !compressed ||
        !scratch || !output || !host_ack_count)
        return -EINVAL;
    if (!source->genuine_original_namespace)
        return -EOPNOTSUPP;
    if (!source->original_selected_source_verified)
        return -EPERM;
    if (!source->immutable_owned_copy)
        return -EPERM;
    if (!source->original_eviction)
        return -EPERM;
    if (!source->decoder_is_retained)
        return -ESTALE;
    if (source->retired_original_decoder)
        return -ESTALE;
    if (!source->no_recompression)
        return -EOPNOTSUPP;
    if (!source->no_secondary_reclaim)
        return -EOPNOTSUPP;
    if (source->representation != ORIGINAL_COMPRESSED_LZO)
        return -EOPNOTSUPP;
    if (source->original_codec != SWAPZ_ZSWAP_IMPORT_LZO1X_CODEC)
        return -EOPNOTSUPP;
    if (source->original_version != SWAPZ_ZSWAP_IMPORT_LZO1X_VERSION)
        return -EOPNOTSUPP;
    if (source->swapz_disk_encoding != SWAPZ_ENCODING_INVALID)
        return -EOPNOTSUPP;
    if (source->logical_page != record->logical_page)
        return -ESTALE;
    if (source->generation != record->generation)
        return -ESTALE;
    if (source->stored_identity != record->stored_entry_identity)
        return -ESTALE;
    if (source->store_generation != record->store_generation)
        return -ESTALE;
    if (source->gc_epoch != record->gc_epoch)
        return -ESTALE;
    if (source->compressed_bytes != record->compressed_length)
        return -EMSGSIZE;
    if (source->source_capacity < source->compressed_bytes)
        return -EMSGSIZE;
    if (source->lower_actual_bytes != source->compressed_bytes)
        return -EIO;
    if (memcmp(source->independent_sha256, record->original_sha256,
               SHA256_DIGEST_LENGTH) != 0)
        return -EBADMSG;
    result = swapz_zswap_import_decoder_owner_decode(
        lease, record, authority, compressed, readable_capacity,
        scratch, SWAPZ_BLOCK_BYTES, output, SWAPZ_BLOCK_BYTES, original_page);
    if (result)
        return result;
    ++(*host_ack_count); /* Only a synthetic host receipt, never an upper BIO. */
    return 0;
}

/* A conventional RAW page is the full ORIGINAL UNCOMPRESSED 4096, not an
 * original compressed LZO stream even if <= the 3568-byte import cap. */
static int read_ordinary_raw_full(const struct host_source_witness *source,
                                  const uint8_t *bytes, uint8_t *output)
{
    uint8_t digest[SHA256_DIGEST_LENGTH];
    if (!source || !bytes || !output)
        return -EINVAL;
    if (source->representation != FULL_UNCOMPRESSED_RAW)
        return -EOPNOTSUPP;
    if (source->original_codec != 0U)
        return -EOPNOTSUPP;
    if (source->compressed_bytes != SWAPZ_BLOCK_BYTES)
        return -EMSGSIZE;
    if (source->source_capacity < SWAPZ_BLOCK_BYTES)
        return -EMSGSIZE;
    if (source->lower_actual_bytes != SWAPZ_BLOCK_BYTES)
        return -EIO;
    if (!SHA256(bytes, SWAPZ_BLOCK_BYTES, digest))
        return -EIO;
    if (memcmp(digest, source->independent_sha256,
               SHA256_DIGEST_LENGTH) != 0)
        return -EBADMSG;
    memcpy(output, bytes, SWAPZ_BLOCK_BYTES);
    return 0;
}

int main(void)
{
    struct swapz_zswap_import_decoder_owner decoder_owner;
    struct swapz_zswap_import_decoder_lease decoder_lease = {0};
    struct swapz_zswap_import_decoder_lease second_lease = {0};
    struct swapz_zswap_import_record record = {0};
    struct swapz_zswap_import_read_authority authority = {0};
    struct host_source_witness source = {0};
    size_t compressed_length = sizeof(real_original_lzo);

    for (uint32_t offset = 0; offset < ORIGINAL_LENGTH; ++offset)
        original_page[offset] = (uint8_t)((offset / 32U) & 3U);
    EXPECT(SHA256(original_page, SWAPZ_BLOCK_BYTES, original_digest) != NULL);
    EXPECT_STATUS(lzo1x_1_compress(original_page, SWAPZ_BLOCK_BYTES,
        real_original_lzo, &compressed_length, compressor_workspace), LZO_E_OK);
    EXPECT(compressed_length > 3U);
    EXPECT(compressed_length <= SWAPZ_MAX_COMPRESSED);
    EXPECT(compressed_length < ORIGINAL_LENGTH);

    EXPECT_STATUS(swapz_zswap_import_decoder_owner_init(&decoder_owner,
        SWAPZ_ZSWAP_IMPORT_LZO1X_CODEC,
        SWAPZ_ZSWAP_IMPORT_LZO1X_VERSION), 0);
    EXPECT_STATUS(swapz_zswap_import_decoder_owner_get(
        &decoder_owner, &decoder_lease), 0);
    EXPECT_STATUS(swapz_zswap_import_decoder_owner_get(
        &decoder_owner, &decoder_lease), -EBUSY);
    EXPECT(decoder_owner.active_readers == 1U);

    record = (struct swapz_zswap_import_record){
        .logical_page = 13U, .generation = 17U,
        .stored_entry_identity = 19U, .store_generation = 23U, .gc_epoch = 29U,
        .compressed_length = (swapz_u32)compressed_length,
        .decoded_length = SWAPZ_BLOCK_BYTES,
        .compressed_crc32c = swapz_crc32c_bytes(
            real_original_lzo, (swapz_u32)compressed_length),
        .representation = SWAPZ_ZSWAP_IMPORT_REPRESENTATION,
        .codec = SWAPZ_ZSWAP_IMPORT_LZO1X_CODEC,
        .version = SWAPZ_ZSWAP_IMPORT_LZO1X_VERSION,
        .stored_eviction = 1U, .immutable_owned_copy = 1U
    };
    memcpy(record.original_sha256, original_digest, SHA256_DIGEST_LENGTH);
    authority = (struct swapz_zswap_import_read_authority){
        .logical_page = record.logical_page,
        .generation = record.generation,
        .stored_entry_identity = record.stored_entry_identity,
        .store_generation = record.store_generation,
        .gc_epoch = record.gc_epoch,
        .actual_lower_read_bytes = record.compressed_length,
        .mapping_published_after_durable_write = 1U, /* HOST ONLY */
        .foreground_write_committed_once = 1U, /* HOST ONLY */
        .upper_write_ack_count = 1U, /* HOST ONLY */
        .current_owned_ram_session = 1U /* HOST ONLY */
    };
    source = (struct host_source_witness){
        .genuine_original_namespace = true,
        .original_selected_source_verified = true, /* FAKE host witness */
        .immutable_owned_copy = true,
        .original_eviction = true,
        .decoder_is_retained = true,
        .no_recompression = true,
        .no_secondary_reclaim = true,
        .representation = ORIGINAL_COMPRESSED_LZO,
        .original_codec = SWAPZ_ZSWAP_IMPORT_LZO1X_CODEC,
        .original_version = SWAPZ_ZSWAP_IMPORT_LZO1X_VERSION,
        .swapz_disk_encoding = SWAPZ_ENCODING_INVALID,
        .logical_page = record.logical_page,
        .generation = record.generation,
        .stored_identity = record.stored_entry_identity,
        .store_generation = record.store_generation,
        .gc_epoch = record.gc_epoch,
        .compressed_bytes = record.compressed_length,
        .source_capacity = record.compressed_length,
        .lower_actual_bytes = record.compressed_length
    };
    memcpy(source.independent_sha256, original_digest, SHA256_DIGEST_LENGTH);

    /* Every semantic mutant of a witness guard is independently compiled
     * and exercised: refusal must preserve the whole output and ACK count.
     */
#define EXPECT_REFUSAL(change, error_code) do { \
        struct host_source_witness candidate = source; \
        memset(output_page, 0xa7, sizeof(output_page)); \
        change; \
        EXPECT_STATUS(guarded_product_lzo_read(&candidate, &decoder_lease, \
            &record, &authority, real_original_lzo, record.compressed_length, \
            scratch_page, output_page, &synthetic_upper_acks), (error_code)); \
        EXPECT(output_page[0] == 0xa7U && \
               output_page[ORIGINAL_LENGTH - 1U] == 0xa7U); \
        EXPECT(synthetic_upper_acks == 0U); \
    } while (0)

    EXPECT_REFUSAL(candidate.genuine_original_namespace = false, -EOPNOTSUPP);
    EXPECT_REFUSAL(candidate.original_selected_source_verified = false, -EPERM);
    EXPECT_REFUSAL(candidate.immutable_owned_copy = false, -EPERM);
    EXPECT_REFUSAL(candidate.original_eviction = false, -EPERM);
    EXPECT_REFUSAL(candidate.decoder_is_retained = false, -ESTALE);
    EXPECT_REFUSAL(candidate.retired_original_decoder = true, -ESTALE);
    EXPECT_REFUSAL(candidate.no_recompression = false, -EOPNOTSUPP);
    EXPECT_REFUSAL(candidate.no_secondary_reclaim = false, -EOPNOTSUPP);
    EXPECT_REFUSAL(candidate.representation = FULL_UNCOMPRESSED_RAW, -EOPNOTSUPP);
    EXPECT_REFUSAL(candidate.original_codec = SWAPZ_DIRECT_ZSWAP_LZ4, -EOPNOTSUPP);
    EXPECT_REFUSAL(candidate.original_codec = 0xffU, -EOPNOTSUPP);
    EXPECT_REFUSAL(candidate.original_version = 0xffU, -EOPNOTSUPP);
    EXPECT_REFUSAL(candidate.swapz_disk_encoding = SWAPZ_ENCODING_DELTA64_SHUF8, -EOPNOTSUPP);
    EXPECT_REFUSAL(candidate.logical_page++, -ESTALE);
    EXPECT_REFUSAL(candidate.generation++, -ESTALE);
    EXPECT_REFUSAL(candidate.stored_identity++, -ESTALE);
    EXPECT_REFUSAL(candidate.store_generation++, -ESTALE);
    EXPECT_REFUSAL(candidate.gc_epoch++, -ESTALE);
    EXPECT_REFUSAL(candidate.compressed_bytes--, -EMSGSIZE);
    EXPECT_REFUSAL(candidate.source_capacity--, -EMSGSIZE);
    EXPECT_REFUSAL(candidate.lower_actual_bytes--, -EIO);
    EXPECT_REFUSAL(candidate.independent_sha256[0] ^= 1U, -EBADMSG);

    /* Real product decode negatives with unmodified host witness. */
#define EXPECT_PRODUCT_REFUSAL(record_change, authority_change, input_ptr, input_capacity, error_code) do { \
        struct swapz_zswap_import_record changed_record = record; \
        struct swapz_zswap_import_read_authority changed_authority = authority; \
        record_change; \
        authority_change; \
        memset(output_page, 0xa7, sizeof(output_page)); \
        EXPECT_STATUS(swapz_zswap_import_decoder_owner_decode(&decoder_lease, \
            &changed_record, &changed_authority, input_ptr, input_capacity, \
            scratch_page, SWAPZ_BLOCK_BYTES, output_page, SWAPZ_BLOCK_BYTES, \
            original_page), (error_code)); \
        EXPECT(output_page[0] == 0xa7U && output_page[ORIGINAL_LENGTH - 1U] == 0xa7U); \
        EXPECT(synthetic_upper_acks == 0U); \
    } while (0)
    EXPECT_PRODUCT_REFUSAL(changed_record.codec = SWAPZ_ZSWAP_IMPORT_LZ4_CODEC,
                           (void)0, real_original_lzo, record.compressed_length, -EOPNOTSUPP);
    EXPECT_PRODUCT_REFUSAL(changed_record.version = 0xffU,
                           (void)0, real_original_lzo, record.compressed_length, -EOPNOTSUPP);
    EXPECT_PRODUCT_REFUSAL(changed_record.decoded_length = SWAPZ_BLOCK_BYTES - 1U,
                           (void)0, real_original_lzo, record.compressed_length, -EMSGSIZE);
    EXPECT_PRODUCT_REFUSAL(changed_record.compressed_length = SWAPZ_MAX_COMPRESSED + 1U,
                           (void)0, real_original_lzo, record.compressed_length, -EMSGSIZE);
    EXPECT_PRODUCT_REFUSAL(changed_record.immutable_owned_copy = 0U,
                           (void)0, real_original_lzo, record.compressed_length, -EOPNOTSUPP);
    EXPECT_PRODUCT_REFUSAL(changed_record.generation++,
                           (void)0, real_original_lzo, record.compressed_length, -ESTALE);
    EXPECT_PRODUCT_REFUSAL((void)0, changed_authority.actual_lower_read_bytes--,
                           real_original_lzo, record.compressed_length, -EIO);
    EXPECT_PRODUCT_REFUSAL((void)0, changed_authority.lower_read_error = -EIO,
                           real_original_lzo, record.compressed_length, -EIO);
    EXPECT_PRODUCT_REFUSAL((void)0, changed_authority.upper_write_ack_count = 0U,
                           real_original_lzo, record.compressed_length, -ESTALE);
    EXPECT_PRODUCT_REFUSAL(changed_record.compressed_crc32c ^= 1U,
                           (void)0, real_original_lzo, record.compressed_length, -EBADMSG);
    EXPECT_PRODUCT_REFUSAL(changed_record.original_sha256[0] ^= 1U,
                           (void)0, real_original_lzo, record.compressed_length, -EBADMSG);
    EXPECT_PRODUCT_REFUSAL((void)0, (void)0, real_original_lzo,
                           record.compressed_length - 1U, -EMSGSIZE);
    memset(output_page, 0xa7, sizeof(output_page));
    EXPECT_STATUS(swapz_zswap_import_decoder_owner_decode(&decoder_lease,
        &record, &authority, real_original_lzo, record.compressed_length,
        scratch_page, SWAPZ_BLOCK_BYTES, scratch_page, SWAPZ_BLOCK_BYTES,
        original_page), -EINVAL);

    /* Original LZO appended byte with matching CRC must reject the kernel's
     * LZO_E_INPUT_NOT_CONSUMED, rather than publishing a partial page. */
    {
        uint8_t trailing[LZO_OUTPUT_CAPACITY];
        struct swapz_zswap_import_record changed_record = record;
        struct swapz_zswap_import_read_authority changed_authority = authority;
        memcpy(trailing, real_original_lzo, compressed_length);
        trailing[compressed_length] = 0x5aU;
        ++changed_record.compressed_length;
        changed_record.compressed_crc32c =
            swapz_crc32c_bytes(trailing, changed_record.compressed_length);
        changed_authority.actual_lower_read_bytes = changed_record.compressed_length;
        memset(output_page, 0xa7, sizeof(output_page));
        EXPECT_STATUS(swapz_zswap_import_decoder_owner_decode(&decoder_lease,
            &changed_record, &changed_authority, trailing,
            changed_record.compressed_length, scratch_page, SWAPZ_BLOCK_BYTES,
            output_page, SWAPZ_BLOCK_BYTES, original_page), -EBADMSG);
        EXPECT(output_page[0] == 0xa7U);
    }

    /* Synthetic 4096-byte uncompressed entry must NEVER be selected as
     * original LZO compressed. The separate raw model requires full page. */
    {
        struct host_source_witness raw = source;
        raw.representation = FULL_UNCOMPRESSED_RAW;
        raw.original_codec = 0U;
        raw.compressed_bytes = ORIGINAL_LENGTH;
        raw.source_capacity = ORIGINAL_LENGTH;
        raw.lower_actual_bytes = ORIGINAL_LENGTH;
        EXPECT_STATUS(read_ordinary_raw_full(&raw, original_page, output_page), 0);
        EXPECT(memcmp(output_page, original_page, ORIGINAL_LENGTH) == 0);
        raw.representation = ORIGINAL_COMPRESSED_LZO;
        EXPECT_STATUS(read_ordinary_raw_full(&raw, real_original_lzo,
                                              output_page), -EOPNOTSUPP);
        raw.representation = FULL_UNCOMPRESSED_RAW;
        raw.compressed_bytes = (uint32_t)compressed_length;
        EXPECT_STATUS(read_ordinary_raw_full(&raw, real_original_lzo,
                                              output_page), -EMSGSIZE);
    }

    /* Finally positive original LZO1X: exact Linux compressor bytes through
     * real product decoder+lease and independent 4096 original SHA. */
    memset(output_page, 0xa7, sizeof(output_page));
    EXPECT_STATUS(guarded_product_lzo_read(&source, &decoder_lease, &record,
        &authority, real_original_lzo, record.compressed_length, scratch_page,
        output_page, &synthetic_upper_acks), 0);
    EXPECT(memcmp(output_page, original_page, ORIGINAL_LENGTH) == 0);
    EXPECT(synthetic_upper_acks == 1U);
    EXPECT_STATUS(swapz_zswap_import_decoder_owner_get(
        &decoder_owner, &second_lease), 0);
    EXPECT_STATUS(swapz_zswap_import_decoder_owner_put(&second_lease), 0);
    /* Start a serialized close while the first original decoder lease is
     * still held. A newly arriving reader is refused; existing reader can
     * still finish with its independently linked original decompressor. */
    EXPECT_STATUS(pthread_mutex_lock(&decoder_owner.lock), 0);
    decoder_owner.closing = 1U;
    EXPECT_STATUS(pthread_mutex_unlock(&decoder_owner.lock), 0);
    EXPECT_STATUS(swapz_zswap_import_decoder_owner_get(
        &decoder_owner, &second_lease), -ESHUTDOWN);
    memset(output_page, 0xa7, sizeof(output_page));
    EXPECT_STATUS(swapz_zswap_import_decoder_owner_decode(&decoder_lease,
        &record, &authority, real_original_lzo, record.compressed_length,
        scratch_page, SWAPZ_BLOCK_BYTES, output_page, SWAPZ_BLOCK_BYTES,
        original_page), 0);
    EXPECT(memcmp(output_page, original_page, ORIGINAL_LENGTH) == 0);
    EXPECT_STATUS(swapz_zswap_import_decoder_owner_put(&decoder_lease), 0);
    EXPECT_STATUS(swapz_zswap_import_decoder_owner_close_and_drain(&decoder_owner), 0);
    EXPECT_STATUS(swapz_zswap_import_decoder_owner_put(&decoder_lease), -EALREADY);
    EXPECT_STATUS(swapz_zswap_import_decoder_owner_get(
        &decoder_owner, &decoder_lease), -ESHUTDOWN);
    printf("PASS round080-agent7 checks=%u genuine_pinned_linux_LZO1X=1 "
           "actual_product_decode_and_lease=1 original4096_sha=1 "
           "RAW_4096=FULL_UNCOMPRESSED original_lzo_import2_not_direct_zstd2=1 "
           "AUTH=0 PHASE_A=BLOCKED\n", checks);
    return 0;
}
