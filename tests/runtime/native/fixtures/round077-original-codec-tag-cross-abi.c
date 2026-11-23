/* SPDX-License-Identifier: GPL-2.0-only */
/*
 * Round077 Agent7: test-only typed boundary between two dormant codec ABIs.
 *
 * Original import tag 2 = LZO1X, direct-handoff tag 2 = ZSTD. A numeric
 * equality is NOT an original codec match. No production bridge is enabled.
 * All "authenticated" flags below are HOST-supplied negative-test witnesses,
 * not actual original STORED/DM proof. One ordered owner holds every buffer.
 */
#include <errno.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <lz4.h>
#include <openssl/sha.h>

#define SOURCE_MAPPED_AUTHENTICATED 0
#define DIRECT_COMPRESSED_HANDOFF 0
#define FORCED_RAW_BYPASS 0
#include "../../../../src/kernel/zswap-direct-handoff.h"
#include "../../../../src/kernel/zswap-import-decoder-owner.h"
#include "../../../../src/kernel/authority.h"

_Static_assert(SWAPZ_DIRECT_ZSWAP_ZSTD == 2, "direct tag 2 is ZSTD");
_Static_assert(SWAPZ_ZSWAP_IMPORT_LZO1X_CODEC == 2U, "import tag 2 is LZO1X");
_Static_assert(SWAPZ_ZSWAP_IMPORT_LZ4_CODEC == 1U, "raw original LZ4");
_Static_assert(SWAPZ_DIRECT_ZSWAP_LZ4 == 1, "direct LZ4 tag");
_Static_assert(SWAPZ_CODEC_METADATA_ON_MEDIA == 0U, "volatile metadata only");
_Static_assert(sizeof(struct swapz_map) == 20U, "volatile map 20 bytes");
_Static_assert(SWAPZ_BLOCK_BYTES == 4096U, "full RAW page");
_Static_assert(SWAPZ_LINUX_SWAP_HEADER_BLOCKS == 1U, "physical header guard");
_Static_assert(SWAPZ_DIRECT_HANDOFF_PRODUCTION_ENABLED == 0U, "direct disabled");
_Static_assert(SWAPZ_ZSWAP_IMPORT_ACTIVE == 0U, "import disabled");
_Static_assert(SOURCE_MAPPED_AUTHENTICATED == 0, "source AUTH disabled");
_Static_assert(DIRECT_COMPRESSED_HANDOFF == 0, "direct path disabled");
_Static_assert(FORCED_RAW_BYPASS == 0, "forced RAW disabled");

enum source_codec_namespace {
    SOURCE_ORIGINAL_IMPORT,
    SOURCE_UNTYPED_DIRECT,
    SOURCE_SWAPZ_DISK,
};
enum source_representation {
    SOURCE_ORIGINAL_COMPRESSED,
    SOURCE_FULL_UNCOMPRESSED,
};

struct source_witness {
    enum source_codec_namespace codec_namespace;
    enum source_representation representation;
    uint8_t original_codec;
    uint8_t original_version;
    uint8_t disk_encoding;
    uint64_t logical_page;
    uint64_t generation;
    uint64_t record_identity;
    uint64_t pool_identity;
    uint64_t dictionary_identity;
    uint64_t codec_generation;
    uint32_t compressed_length;
    uint32_t readable_capacity;
    uint32_t actual_lower_read_bytes;
    uint8_t independent_original_sha256[SHA256_DIGEST_LENGTH];
    bool original_source_witness; /* Host assertion, NOT real source AUTH. */
    bool original_eviction;
    bool owns_immutable_copy;
    bool original_decoder_retained;
    bool decoder_retired;
    bool raw_lz4_unframed;
    bool requests_recompression;
    bool requests_secondary_reclaim;
};

struct raw_witness {
    enum source_representation representation;
    uint8_t original_codec;
    uint32_t input_length;
    uint32_t readable_capacity;
    uint32_t actual_lower_read_bytes;
    uint8_t independent_original_sha256[SHA256_DIGEST_LENGTH];
};

static uint32_t directed_checks;
static uint32_t decode_callback_count;
static uint8_t original_page[SWAPZ_BLOCK_BYTES];
static uint8_t raw_lz4[SWAPZ_BLOCK_BYTES];
static uint8_t expected_sha256[SHA256_DIGEST_LENGTH];
static uint8_t original_import_output[SWAPZ_BLOCK_BYTES];
static uint8_t output_page[SWAPZ_BLOCK_BYTES];
static uint8_t scratch_page[SWAPZ_BLOCK_BYTES];

#define CHECK(condition) do { \
    ++directed_checks; \
    if (!(condition)) { \
        fprintf(stderr, "FIRST_ERROR line=%d check=%s\n", __LINE__, #condition); \
        return 1; \
    } \
} while (0)
#define CHECK_RESULT(actual, expected) CHECK((actual) == (expected))

static int decode_raw_lz4(const swapz_direct_u8 *compressed,
                          swapz_direct_u32 compressed_length,
                          swapz_direct_u8 *page,
                          swapz_direct_u32 page_capacity,
                          swapz_direct_u32 *decoded_length, void *context)
{
    int decoded;
    (void)context;
    ++decode_callback_count;
    if (compressed_length > SWAPZ_MAX_COMPRESSED ||
        page_capacity != SWAPZ_BLOCK_BYTES || !decoded_length)
        return -EINVAL;
    decoded = LZ4_decompress_safe((const char *)compressed, (char *)page,
                                  (int)compressed_length, (int)page_capacity);
    if (decoded < 0)
        return -EBADMSG;
    *decoded_length = (swapz_direct_u32)decoded;
    return 0;
}

static int host_crc32c(const swapz_direct_u8 *bytes,
                       swapz_direct_u32 length, swapz_direct_u32 *digest,
                       void *context)
{
    (void)context;
    if (!bytes || !digest)
        return -EINVAL;
    *digest = swapz_crc32c_bytes(bytes, length);
    return 0;
}

static int host_sha256(const swapz_direct_u8 *bytes,
                       swapz_direct_u32 length,
                       swapz_direct_u8 digest[SWAPZ_DIRECT_SHA256_BYTES],
                       void *context)
{
    (void)context;
    return SHA256(bytes, length, digest) ? 0 : -EIO;
}

/*
 * Test-only narrow bridge. An enum of the OTHER ABI can never be passed as
 * untyped int and converted to this ORIGINAL codec. No LZO1X direct decoder
 * exists in the dormant direct registry: fail closed, do not claim ZSTD.
 * The returned value cannot authenticate Linux MM's original source.
 */
static int host_typed_original_read(
    const struct source_witness *source,
    const struct swapz_direct_ram_descriptor *descriptor,
    const struct swapz_direct_read_identity *expected,
    const struct swapz_zswap_import_decoder_lease *original_lease,
    const struct swapz_direct_decoder *direct_decoder,
    const struct swapz_direct_integrity *integrity,
    uint8_t output[SWAPZ_BLOCK_BYTES])
{
    uint8_t local_scratch[SWAPZ_BLOCK_BYTES];
    if (!source || !descriptor || !expected || !original_lease ||
        !direct_decoder || !integrity || !output)
        return -EINVAL;
    if (source->codec_namespace != SOURCE_ORIGINAL_IMPORT)
        return -EOPNOTSUPP;
    if (source->representation != SOURCE_ORIGINAL_COMPRESSED)
        return -EOPNOTSUPP;
    if (!source->original_source_witness)
        return -EPERM;
    if (!source->original_eviction)
        return -EPERM;
    if (!source->owns_immutable_copy)
        return -EPERM;
    if (!source->original_decoder_retained)
        return -ESTALE;
    if (source->decoder_retired)
        return -ESTALE;
    if (source->original_codec != SWAPZ_ZSWAP_IMPORT_LZ4_CODEC)
        return -EOPNOTSUPP;
    if (source->original_version != SWAPZ_ZSWAP_IMPORT_VERSION)
        return -EOPNOTSUPP;
    if (descriptor->codec != SWAPZ_DIRECT_ZSWAP_LZ4)
        return -EOPNOTSUPP;
    if (!original_lease->owner ||
        original_lease->codec != SWAPZ_ZSWAP_IMPORT_LZ4_CODEC)
        return -EOPNOTSUPP;
    if (original_lease->version != SWAPZ_ZSWAP_IMPORT_VERSION)
        return -EOPNOTSUPP;
    if (!source->raw_lz4_unframed)
        return -EOPNOTSUPP;
    if (source->disk_encoding != SWAPZ_ENCODING_INVALID)
        return -EOPNOTSUPP;
    if (source->requests_recompression)
        return -EOPNOTSUPP;
    if (source->requests_secondary_reclaim)
        return -EOPNOTSUPP;
    if (source->logical_page != descriptor->logical_page)
        return -ESTALE;
    if (source->generation != descriptor->generation)
        return -ESTALE;
    if (source->record_identity != descriptor->source_record_identity)
        return -ESTALE;
    if (source->pool_identity != descriptor->pool_identity)
        return -ESTALE;
    if (source->dictionary_identity != descriptor->dictionary_identity)
        return -ESTALE;
    if (source->codec_generation != descriptor->codec_generation)
        return -ESTALE;
    if (source->compressed_length != descriptor->compressed_length)
        return -EMSGSIZE;
    if (source->readable_capacity < descriptor->compressed_length)
        return -EMSGSIZE;
    if (source->actual_lower_read_bytes != descriptor->compressed_length)
        return -EIO;
    if (memcmp(source->independent_original_sha256,
               descriptor->expected_page_sha256, SHA256_DIGEST_LENGTH) != 0)
        return -EBADMSG;
    return swapz_direct_readback(descriptor, expected, direct_decoder,
                                 integrity, local_scratch, output);
}

/* Ordinary RAW is a complete original UNCOMPRESSED page and NEVER compressed
 * original bytes carried by a different codec family. This is HOST only,
 * not the production raw publication path already qualified in Round074.
 */
static int host_full_raw_read(const struct raw_witness *source,
                             const uint8_t *full_page,
                             uint8_t result[SWAPZ_BLOCK_BYTES])
{
    uint8_t digest[SHA256_DIGEST_LENGTH];
    if (!source || !full_page || !result)
        return -EINVAL;
    if (source->representation != SOURCE_FULL_UNCOMPRESSED)
        return -EOPNOTSUPP;
    if (source->original_codec != 0U)
        return -EOPNOTSUPP;
    if (source->input_length != SWAPZ_BLOCK_BYTES)
        return -EMSGSIZE;
    if (source->readable_capacity < SWAPZ_BLOCK_BYTES)
        return -EMSGSIZE;
    if (source->actual_lower_read_bytes != SWAPZ_BLOCK_BYTES)
        return -EIO;
    if (!SHA256(full_page, SWAPZ_BLOCK_BYTES, digest))
        return -EIO;
    if (memcmp(digest, source->independent_original_sha256,
               SHA256_DIGEST_LENGTH) != 0)
        return -EBADMSG;
    memcpy(result, full_page, SWAPZ_BLOCK_BYTES);
    return 0;
}

int main(void)
{
    struct swapz_zswap_import_decoder_owner original_owner;
    struct swapz_zswap_import_decoder_lease original_lease = {0};
    struct swapz_zswap_import_decoder_owner lzo_owner;
    struct swapz_zswap_import_decoder_lease lzo_lease = {0};
    struct swapz_zswap_import_record import_record = {0};
    struct swapz_zswap_import_read_authority import_authority = {0};
    struct swapz_direct_ram_descriptor descriptor = {0};
    struct swapz_direct_read_identity expected = {0};
    struct swapz_direct_decoder direct_decoder = {0};
    struct swapz_direct_integrity integrity = {0};
    struct source_witness source = {0};
    struct raw_witness raw = {0};
    int compressed_length;

    for (uint32_t offset = 0; offset < SWAPZ_BLOCK_BYTES; ++offset)
        original_page[offset] = (uint8_t)((offset / 32U) & 7U);
    CHECK(SHA256(original_page, SWAPZ_BLOCK_BYTES, expected_sha256) != NULL);
    compressed_length = LZ4_compress_default(
        (const char *)original_page, (char *)raw_lz4,
        (int)SWAPZ_BLOCK_BYTES, (int)sizeof(raw_lz4));
    CHECK(compressed_length > 0 &&
          compressed_length <= (int)SWAPZ_MAX_COMPRESSED);

    CHECK_RESULT(swapz_zswap_import_decoder_owner_init(
        &original_owner, SWAPZ_ZSWAP_IMPORT_LZ4_CODEC,
        SWAPZ_ZSWAP_IMPORT_VERSION), 0);
    CHECK_RESULT(swapz_zswap_import_decoder_owner_get(
        &original_owner, &original_lease), 0);
    import_record.logical_page = 11U;
    import_record.generation = 13U;
    import_record.stored_entry_identity = 19U;
    import_record.store_generation = 17U;
    import_record.gc_epoch = 23U;
    import_record.compressed_length = (swapz_u32)compressed_length;
    import_record.decoded_length = SWAPZ_BLOCK_BYTES;
    import_record.compressed_crc32c =
        swapz_crc32c_bytes(raw_lz4, (swapz_u32)compressed_length);
    import_record.representation = SWAPZ_ZSWAP_IMPORT_REPRESENTATION;
    import_record.codec = SWAPZ_ZSWAP_IMPORT_LZ4_CODEC;
    import_record.version = SWAPZ_ZSWAP_IMPORT_VERSION;
    import_record.stored_eviction = 1U;
    import_record.immutable_owned_copy = 1U;
    memcpy(import_record.original_sha256, expected_sha256,
           SHA256_DIGEST_LENGTH);
    import_authority.logical_page = import_record.logical_page;
    import_authority.generation = import_record.generation;
    import_authority.stored_entry_identity = import_record.stored_entry_identity;
    import_authority.store_generation = import_record.store_generation;
    import_authority.gc_epoch = import_record.gc_epoch;
    import_authority.actual_lower_read_bytes = (swapz_u32)compressed_length;
    import_authority.mapping_published_after_durable_write = 1U;
    import_authority.foreground_write_committed_once = 1U;
    import_authority.upper_write_ack_count = 1U;
    import_authority.current_owned_ram_session = 1U;
    CHECK_RESULT(swapz_zswap_import_decoder_owner_decode(
        &original_lease, &import_record, &import_authority,
        raw_lz4, (swapz_u32)compressed_length, scratch_page, SWAPZ_BLOCK_BYTES,
        original_import_output, SWAPZ_BLOCK_BYTES, original_page), 0);
    CHECK(memcmp(original_import_output, original_page,
                 SWAPZ_BLOCK_BYTES) == 0);

    descriptor.version = SWAPZ_DIRECT_HANDOFF_VERSION;
    descriptor.semantic_origin = SWAPZ_DIRECT_AUTHENTICATED_STORED;
    descriptor.representation = SWAPZ_DIRECT_ZSWAP_COMPRESSED;
    descriptor.codec = SWAPZ_DIRECT_ZSWAP_LZ4;
    descriptor.payload_lifetime = SWAPZ_DIRECT_IMMUTABLY_OWNED;
    descriptor.logical_bytes = SWAPZ_BLOCK_BYTES;
    descriptor.compressed_length = (swapz_direct_u32)compressed_length;
    descriptor.logical_page = import_record.logical_page;
    descriptor.generation = import_record.generation;
    descriptor.source_record_identity = import_record.stored_entry_identity;
    descriptor.pool_identity = 29U;
    descriptor.dictionary_identity = 0U;
    descriptor.codec_generation = 31U;
    descriptor.payload = raw_lz4;
    descriptor.payload_crc32c = import_record.compressed_crc32c;
    memcpy(descriptor.expected_page_sha256, expected_sha256,
           SHA256_DIGEST_LENGTH);
    expected.logical_page = descriptor.logical_page;
    expected.generation = descriptor.generation;
    expected.source_record_identity = descriptor.source_record_identity;
    direct_decoder.codec = SWAPZ_DIRECT_ZSWAP_LZ4;
    direct_decoder.pool_identity = descriptor.pool_identity;
    direct_decoder.dictionary_identity = descriptor.dictionary_identity;
    direct_decoder.codec_generation = descriptor.codec_generation;
    direct_decoder.decode = decode_raw_lz4;
    integrity.crc32c = host_crc32c;
    integrity.sha256 = host_sha256;
    source = (struct source_witness) {
        .codec_namespace = SOURCE_ORIGINAL_IMPORT,
        .representation = SOURCE_ORIGINAL_COMPRESSED,
        .original_codec = SWAPZ_ZSWAP_IMPORT_LZ4_CODEC,
        .original_version = SWAPZ_ZSWAP_IMPORT_VERSION,
        .disk_encoding = SWAPZ_ENCODING_INVALID,
        .logical_page = descriptor.logical_page,
        .generation = descriptor.generation,
        .record_identity = descriptor.source_record_identity,
        .pool_identity = descriptor.pool_identity,
        .dictionary_identity = descriptor.dictionary_identity,
        .codec_generation = descriptor.codec_generation,
        .compressed_length = descriptor.compressed_length,
        .readable_capacity = descriptor.compressed_length,
        .actual_lower_read_bytes = descriptor.compressed_length,
        .original_source_witness = true,
        .original_eviction = true,
        .owns_immutable_copy = true,
        .original_decoder_retained = true,
        .raw_lz4_unframed = true
    };
    memcpy(source.independent_original_sha256, expected_sha256,
           SHA256_DIGEST_LENGTH);

    /* Demonstrate the numeric collision on the REAL direct validator: a
     * maliciously relabeled tag2 ZSTD matches a synthetic direct decoder.
     * This is NOT a working original LZO1X decoder. The typed witness below
     * must refuse it before any decode callback or upper output.
     */
    {
        struct swapz_direct_ram_descriptor wrong = descriptor;
        struct swapz_direct_decoder synthetic = direct_decoder;
        struct source_witness original_lzo = source;
        wrong.codec = SWAPZ_DIRECT_ZSWAP_ZSTD;
        synthetic.codec = SWAPZ_DIRECT_ZSWAP_ZSTD;
        original_lzo.original_codec = SWAPZ_ZSWAP_IMPORT_LZO1X_CODEC;
        CHECK_RESULT(swapz_direct_validate(&wrong, &expected,
                                            &synthetic, &integrity), 0);
        memset(output_page, 0x7b, sizeof(output_page));
        CHECK_RESULT(host_typed_original_read(&original_lzo, &wrong,
            &expected, &original_lease, &synthetic, &integrity,
            output_page), -EOPNOTSUPP);
        CHECK(decode_callback_count == 0U);
        CHECK(output_page[0] == 0x7bU && output_page[SWAPZ_BLOCK_BYTES - 1U] == 0x7bU);
    }

    /* Each disabled guard is its own separately compiled/executed semantic
     * mutant. A real source linked validator may accept tag2 numerically,
     * but the HOST-only typed boundary refuses all mixed/unknown identities.
     */
#define EXPECT_REJECT(change, failure) do { \
        struct source_witness candidate = source; \
        struct swapz_direct_ram_descriptor trial = descriptor; \
        struct swapz_zswap_import_decoder_lease trial_lease = original_lease; \
        struct swapz_direct_decoder trial_decoder = direct_decoder; \
        change; \
        memset(output_page, 0x7b, sizeof(output_page)); \
        CHECK_RESULT(host_typed_original_read(&candidate, &trial, \
            &expected, &trial_lease, &trial_decoder, &integrity, \
            output_page), (failure)); \
        CHECK(decode_callback_count == 0U); \
        CHECK(output_page[0] == 0x7bU && output_page[SWAPZ_BLOCK_BYTES - 1U] == 0x7bU); \
    } while (0)
    EXPECT_REJECT(candidate.codec_namespace = SOURCE_UNTYPED_DIRECT, -EOPNOTSUPP);
    EXPECT_REJECT(candidate.codec_namespace = SOURCE_SWAPZ_DISK, -EOPNOTSUPP);
    EXPECT_REJECT(candidate.representation = SOURCE_FULL_UNCOMPRESSED, -EOPNOTSUPP);
    EXPECT_REJECT(candidate.original_source_witness = false, -EPERM);
    EXPECT_REJECT(candidate.original_eviction = false, -EPERM);
    EXPECT_REJECT(candidate.owns_immutable_copy = false, -EPERM);
    EXPECT_REJECT(candidate.original_decoder_retained = false, -ESTALE);
    EXPECT_REJECT(candidate.decoder_retired = true, -ESTALE);
    EXPECT_REJECT(candidate.original_codec = SWAPZ_ZSWAP_IMPORT_LZO1X_CODEC, -EOPNOTSUPP);
    EXPECT_REJECT(candidate.original_codec = 0xffU, -EOPNOTSUPP);
    EXPECT_REJECT(candidate.original_version = 0xffU, -EOPNOTSUPP);
    EXPECT_REJECT(trial.codec = SWAPZ_DIRECT_ZSWAP_ZSTD; trial_decoder.codec = SWAPZ_DIRECT_ZSWAP_ZSTD, -EOPNOTSUPP);
    EXPECT_REJECT(trial_lease.codec = SWAPZ_ZSWAP_IMPORT_LZO1X_CODEC, -EOPNOTSUPP);
    EXPECT_REJECT(trial_lease.version = 0xffU, -EOPNOTSUPP);
    EXPECT_REJECT(candidate.raw_lz4_unframed = false, -EOPNOTSUPP);
    EXPECT_REJECT(candidate.disk_encoding = SWAPZ_ENCODING_LZ4, -EOPNOTSUPP);
    EXPECT_REJECT(candidate.disk_encoding = SWAPZ_ENCODING_DELTA64_SHUF8, -EOPNOTSUPP);
    EXPECT_REJECT(candidate.requests_recompression = true, -EOPNOTSUPP);
    EXPECT_REJECT(candidate.requests_secondary_reclaim = true, -EOPNOTSUPP);
    EXPECT_REJECT(candidate.logical_page++, -ESTALE);
    EXPECT_REJECT(candidate.generation++, -ESTALE);
    EXPECT_REJECT(candidate.record_identity++, -ESTALE);
    EXPECT_REJECT(candidate.pool_identity++, -ESTALE);
    EXPECT_REJECT(candidate.dictionary_identity++, -ESTALE);
    EXPECT_REJECT(candidate.codec_generation++, -ESTALE);
    EXPECT_REJECT(candidate.compressed_length--, -EMSGSIZE);
    EXPECT_REJECT(candidate.readable_capacity--, -EMSGSIZE);
    EXPECT_REJECT(candidate.actual_lower_read_bytes--, -EIO);
    EXPECT_REJECT(candidate.independent_original_sha256[0] ^= 1U, -EBADMSG);

    CHECK_RESULT(swapz_zswap_import_decoder_owner_init(
        &lzo_owner, SWAPZ_ZSWAP_IMPORT_LZO1X_CODEC,
        SWAPZ_ZSWAP_IMPORT_LZO1X_VERSION), 0);
    CHECK_RESULT(swapz_zswap_import_decoder_owner_get(&lzo_owner, &lzo_lease), 0);
    {
        struct swapz_zswap_import_record lzo_record = import_record;
        lzo_record.codec = SWAPZ_ZSWAP_IMPORT_LZO1X_CODEC;
        lzo_record.version = SWAPZ_ZSWAP_IMPORT_LZO1X_VERSION;
        CHECK_RESULT(swapz_zswap_import_decoder_owner_decode(
            &lzo_lease, &lzo_record, &import_authority,
            raw_lz4, (swapz_u32)compressed_length,
            scratch_page, SWAPZ_BLOCK_BYTES, original_import_output,
            SWAPZ_BLOCK_BYTES, original_page), -EOPNOTSUPP);
    }
    CHECK_RESULT(swapz_zswap_import_decoder_owner_put(&lzo_lease), 0);
    CHECK_RESULT(swapz_zswap_import_decoder_owner_close_and_drain(&lzo_owner), 0);
    CHECK_RESULT(swapz_zswap_import_decoder_owner_put(&lzo_lease), -EALREADY);
    memset(output_page, 0x7b, sizeof(output_page));
    CHECK_RESULT(host_typed_original_read(&source, &descriptor, &expected,
        &original_lease, &direct_decoder, &integrity, output_page), 0);
    CHECK(decode_callback_count == 1U);
    CHECK(memcmp(output_page, original_page, SWAPZ_BLOCK_BYTES) == 0);
    CHECK_RESULT(swapz_zswap_import_decoder_owner_put(&original_lease), 0);
    CHECK_RESULT(swapz_zswap_import_decoder_owner_close_and_drain(&original_owner), 0);
    CHECK_RESULT(swapz_zswap_import_decoder_owner_get(&original_owner,
                                                      &original_lease), -ESHUTDOWN);

    raw = (struct raw_witness){
        .representation = SOURCE_FULL_UNCOMPRESSED,
        .input_length = SWAPZ_BLOCK_BYTES,
        .readable_capacity = SWAPZ_BLOCK_BYTES,
        .actual_lower_read_bytes = SWAPZ_BLOCK_BYTES
    };
    memcpy(raw.independent_original_sha256, expected_sha256,
           SHA256_DIGEST_LENGTH);
    memset(output_page, 0x7b, sizeof(output_page));
#define EXPECT_RAW_REJECT(change, failure) do { \
        struct raw_witness candidate = raw; \
        change; \
        memset(output_page, 0x7b, sizeof(output_page)); \
        CHECK_RESULT(host_full_raw_read(&candidate, original_page, \
                                          output_page), (failure)); \
        CHECK(output_page[0] == 0x7bU && output_page[SWAPZ_BLOCK_BYTES - 1U] == 0x7bU); \
    } while (0)
    EXPECT_RAW_REJECT(candidate.representation = SOURCE_ORIGINAL_COMPRESSED, -EOPNOTSUPP);
    EXPECT_RAW_REJECT(candidate.original_codec = SWAPZ_ZSWAP_IMPORT_LZO1X_CODEC, -EOPNOTSUPP);
    EXPECT_RAW_REJECT(candidate.input_length = SWAPZ_BLOCK_BYTES - 1U, -EMSGSIZE);
    EXPECT_RAW_REJECT(candidate.readable_capacity = SWAPZ_BLOCK_BYTES - 1U, -EMSGSIZE);
    EXPECT_RAW_REJECT(candidate.actual_lower_read_bytes = SWAPZ_BLOCK_BYTES - 1U, -EIO);
    EXPECT_RAW_REJECT(candidate.independent_original_sha256[0] ^= 1U, -EBADMSG);
    {
        struct raw_witness compressed_alias = raw;
        compressed_alias.representation = SOURCE_ORIGINAL_COMPRESSED;
        compressed_alias.original_codec = SWAPZ_ZSWAP_IMPORT_LZ4_CODEC;
        compressed_alias.input_length = (uint32_t)compressed_length;
        compressed_alias.readable_capacity = (uint32_t)compressed_length;
        compressed_alias.actual_lower_read_bytes = (uint32_t)compressed_length;
        CHECK_RESULT(host_full_raw_read(&compressed_alias, raw_lz4,
            output_page), -EOPNOTSUPP);
    }
    CHECK_RESULT(host_full_raw_read(&raw, original_page, output_page), 0);
    CHECK(memcmp(output_page, original_page, SWAPZ_BLOCK_BYTES) == 0);
    printf("PASS round077-agent7 assertions=%u direct2=ZSTD import2=LZO1X "
           "typed_cross_abi_refused=1 raw4096=FULL_ORIGINAL_UNCOMPRESSED "
           "actual_import_decoder_lease=1 original_lzo_decode=NOT_RUN "
           "AUTH=0 PHASE_A=BLOCKED\n", directed_checks);
    return 0;
}
