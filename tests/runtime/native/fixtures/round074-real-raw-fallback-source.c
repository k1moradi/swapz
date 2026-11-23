/* SPDX-License-Identifier: GPL-2.0-only */
/*
 * Round074 Agent7: real product RAW authority with HOST-ONLY pre-admission.
 * One serialized owner; no authenticated Linux zswap STORED source, kernel BIO,
 * real FUA/upper ACK, recompression, secondary eviction, or physical device.
 */
#include <errno.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <lz4.h>
#include <openssl/sha.h>

#define SWAPZ_ZSWAP_IMPORT_HOST_TEST 1
#define SOURCE_MAPPED_AUTHENTICATED 0
#define DIRECT_COMPRESSED_HANDOFF 0
#define FORCED_RAW_BYPASS 0
#include "../../../../src/kernel/zswap-import-codec.h"
#include "../../../../src/kernel/zswap-direct-handoff.h"
#include "../../../../src/kernel/authority.h"

_Static_assert(sizeof(struct swapz_map) == 20U, "volatile map");
_Static_assert(SWAPZ_BLOCK_BYTES == 4096U, "full RAW 4096");
_Static_assert(SWAPZ_CODEC_METADATA_ON_MEDIA == 0U, "metadata in RAM");
_Static_assert(SWAPZ_ZSWAP_IMPORT_ACTIVE == 0U, "import disabled");
_Static_assert(SWAPZ_DIRECT_HANDOFF_PRODUCTION_ENABLED == 0U, "handoff disabled");
_Static_assert(SOURCE_MAPPED_AUTHENTICATED == 0, "source auth disabled");
_Static_assert(DIRECT_COMPRESSED_HANDOFF == 0, "direct disabled");
_Static_assert(FORCED_RAW_BYPASS == 0, "forced RAW disabled");

enum { LOGICAL_PAGES = 16U, DATA_BLOCKS = 2048U };
enum source_kind { FULL_UNCOMPRESSED, ORIGINAL_COMPRESSED };

struct fallback_request {
    const uint8_t *bytes;
    uint32_t length;
    uint32_t readable_capacity;
    uint64_t original_epoch;
    uint64_t expected_epoch;
    uint64_t original_identity;
    uint64_t expected_identity;
    enum source_kind kind;
    uint8_t original_codec;
    uint8_t original_codec_version;
    uint8_t disk_encoding;
    uint8_t independent_sha256[SHA256_DIGEST_LENGTH];
    bool full_page_authenticated; /* Only a test-supplied witness. */
    bool immutable_owned;
    bool codec_retired;
    bool wants_recompression;
    bool duplicate_upper_ack;
    bool lower_write_complete;    /* Only a HOST modeled receipt. */
    bool lower_flush_complete;    /* Only a HOST modeled receipt. */
};

struct host_owner {
    struct swapz_authority authority;
    struct swapz_map maps[LOGICAL_PAGES];
    swapz_u16 live_records[DATA_BLOCKS];
    swapz_u8 extent_classes[DATA_BLOCKS];
    uint8_t memory_lower[2U * SWAPZ_BLOCK_BYTES];
    uint8_t preserved_header[SWAPZ_BLOCK_BYTES];
    uint8_t expected_sha256[SHA256_DIGEST_LENGTH];
    uint32_t synthetic_upper_acks;
};
static struct host_owner owner;
static uint32_t directed_checks;

#define REQUIRE(condition) do { \
    ++directed_checks; \
    if (!(condition)) { \
        fprintf(stderr, "FIRST_ERROR line=%d check=%s\n", __LINE__, #condition); \
        return 1; \
    } \
} while (0)
#define REQUIRE_STATUS(actual, expected) REQUIRE((actual) == (expected))

/* Entirely HOST-owned admission model, not a production entry point. */
static int validate_full_original(const struct fallback_request *source)
{
    uint8_t digest[SHA256_DIGEST_LENGTH];
    if (!source || !source->bytes)
        return -EINVAL;
    if (source->kind != FULL_UNCOMPRESSED)
        return -EOPNOTSUPP;
    if (source->original_codec != 0U)
        return -EOPNOTSUPP;
    if (source->original_codec_version != 0U)
        return -EOPNOTSUPP;
    if (source->disk_encoding != SWAPZ_ENCODING_INVALID)
        return -EOPNOTSUPP;
    if (!source->full_page_authenticated)
        return -EPERM;
    if (!source->immutable_owned)
        return -EPERM;
    if (source->codec_retired)
        return -ESTALE;
    if (source->original_epoch != source->expected_epoch)
        return -ESTALE;
    if (source->original_identity != source->expected_identity)
        return -ESTALE;
    if (source->length != SWAPZ_BLOCK_BYTES)
        return -EMSGSIZE;
    if (source->readable_capacity < SWAPZ_BLOCK_BYTES)
        return -EMSGSIZE;
    if (source->wants_recompression)
        return -EOPNOTSUPP;
    if (source->duplicate_upper_ack)
        return -EALREADY;
    if (!source->lower_write_complete)
        return -EIO;
    if (!source->lower_flush_complete)
        return -EIO;
    if (!SHA256(source->bytes, SWAPZ_BLOCK_BYTES, digest))
        return -EIO;
    if (memcmp(digest, source->independent_sha256, sizeof(digest)) != 0)
        return -EBADMSG;
    return 0;
}

/* Actual product stage + full RAW publication, model lower receipts only. */
static int host_raw_publish(const struct fallback_request *source)
{
    const swapz_u32 logical_page = 1U;
    struct swapz_tx transaction;
    int status = validate_full_original(source);
    if (status)
        return status;
    status = swapz_stage(&owner.authority, &logical_page, 1U, 1U, &transaction);
    if (status)
        return status;
    if (transaction.start_block != 0U) {
        (void)swapz_abort(&owner.authority, &transaction);
        return -ERANGE; /* Only one data block provisioned in this model. */
    }
    memcpy(owner.memory_lower + SWAPZ_BLOCK_BYTES, source->bytes,
           SWAPZ_BLOCK_BYTES);
    status = swapz_finish_raw(&owner.authority, &transaction,
                              owner.memory_lower + SWAPZ_BLOCK_BYTES, 1U, 0);
    if (status)
        return status;
    ++owner.synthetic_upper_acks;
    return 0;
}

static int host_raw_read(uint32_t actual_lower_bytes,
                         uint8_t output[SWAPZ_BLOCK_BYTES])
{
    uint8_t digest[SHA256_DIGEST_LENGTH];
    const uint8_t *const stored = owner.memory_lower + SWAPZ_BLOCK_BYTES;
    if (!output)
        return -EINVAL;
    if (actual_lower_bytes != SWAPZ_BLOCK_BYTES)
        return -EIO;
    int status = swapz_verify_raw(&owner.authority, 1U, stored);
    if (status)
        return status;
    if (!SHA256(stored, SWAPZ_BLOCK_BYTES, digest))
        return -EIO;
    if (memcmp(digest, owner.expected_sha256, sizeof(digest)) != 0)
        return -EBADMSG;
    memcpy(output, stored, SWAPZ_BLOCK_BYTES);
    return 0;
}

int main(void)
{
    static uint8_t original_page[SWAPZ_BLOCK_BYTES];
    static uint8_t compressed_original[SWAPZ_BLOCK_BYTES];
    static uint8_t decoded_page[SWAPZ_BLOCK_BYTES];
    struct fallback_request source = {0};
    int compressed_bytes;
    for (uint32_t index = 0; index < SWAPZ_BLOCK_BYTES; ++index)
        original_page[index] = (uint8_t)((index / 64U) & 3U);
    REQUIRE(SHA256(original_page, SWAPZ_BLOCK_BYTES, owner.expected_sha256) != NULL);
    compressed_bytes = LZ4_compress_default((const char *)original_page,
            (char *)compressed_original, (int)SWAPZ_BLOCK_BYTES,
            (int)sizeof(compressed_original));
    REQUIRE(compressed_bytes > 0 && compressed_bytes <= (int)SWAPZ_MAX_COMPRESSED);
    REQUIRE_STATUS(swapz_authority_init(&owner.authority, owner.maps,
            owner.live_records, owner.extent_classes,
            LOGICAL_PAGES, DATA_BLOCKS), 0);
    for (uint32_t index = 0; index < SWAPZ_BLOCK_BYTES; ++index)
        owner.memory_lower[index] = (uint8_t)(index * 37U + 0x51U);
    memcpy(owner.preserved_header, owner.memory_lower, SWAPZ_BLOCK_BYTES);
    memset(owner.memory_lower + SWAPZ_BLOCK_BYTES, 0xa5, SWAPZ_BLOCK_BYTES);
    source = (struct fallback_request){
        .bytes = original_page, .length = SWAPZ_BLOCK_BYTES,
        .readable_capacity = SWAPZ_BLOCK_BYTES,
        .original_epoch = 19U, .expected_epoch = 19U,
        .original_identity = 23U, .expected_identity = 23U,
        .kind = FULL_UNCOMPRESSED, .disk_encoding = SWAPZ_ENCODING_INVALID,
        .full_page_authenticated = true, .immutable_owned = true,
        .lower_write_complete = true, .lower_flush_complete = true
    };
    memcpy(source.independent_sha256, owner.expected_sha256,
           sizeof(source.independent_sha256));

    /* The real product map cannot be touched on any refused host request. */
#define EXPECT_REFUSED(change, failure) do { \
        struct fallback_request candidate = source; \
        change; \
        REQUIRE_STATUS(host_raw_publish(&candidate), (failure)); \
        REQUIRE(owner.synthetic_upper_acks == 0U); \
        REQUIRE(owner.authority.next_block == 0U); \
        REQUIRE(!owner.maps[1U].valid); \
        REQUIRE(memcmp(owner.memory_lower, owner.preserved_header, SWAPZ_BLOCK_BYTES) == 0); \
    } while (0)
    EXPECT_REFUSED(candidate.kind = ORIGINAL_COMPRESSED, -EOPNOTSUPP);
    EXPECT_REFUSED(candidate.original_codec = SWAPZ_ZSWAP_IMPORT_LZ4_CODEC, -EOPNOTSUPP);
    EXPECT_REFUSED(candidate.original_codec = SWAPZ_ZSWAP_IMPORT_LZO1X_CODEC, -EOPNOTSUPP);
    EXPECT_REFUSED(candidate.original_codec_version = SWAPZ_ZSWAP_IMPORT_VERSION, -EOPNOTSUPP);
    EXPECT_REFUSED(candidate.disk_encoding = SWAPZ_ENCODING_LZ4, -EOPNOTSUPP);
    EXPECT_REFUSED(candidate.disk_encoding = SWAPZ_ENCODING_DELTA64, -EOPNOTSUPP);
    EXPECT_REFUSED(candidate.disk_encoding = SWAPZ_ENCODING_DELTA64_SHUF8, -EOPNOTSUPP);
    EXPECT_REFUSED(candidate.full_page_authenticated = false, -EPERM);
    EXPECT_REFUSED(candidate.immutable_owned = false, -EPERM);
    EXPECT_REFUSED(candidate.codec_retired = true, -ESTALE);
    EXPECT_REFUSED(candidate.expected_epoch++, -ESTALE);
    EXPECT_REFUSED(candidate.expected_identity++, -ESTALE);
    EXPECT_REFUSED(candidate.length = SWAPZ_BLOCK_BYTES - 1U, -EMSGSIZE);
    EXPECT_REFUSED(candidate.readable_capacity = SWAPZ_BLOCK_BYTES - 1U, -EMSGSIZE);
    EXPECT_REFUSED(candidate.wants_recompression = true, -EOPNOTSUPP);
    EXPECT_REFUSED(candidate.duplicate_upper_ack = true, -EALREADY);
    EXPECT_REFUSED(candidate.lower_write_complete = false, -EIO);
    EXPECT_REFUSED(candidate.lower_flush_complete = false, -EIO);
    EXPECT_REFUSED(candidate.independent_sha256[0] ^= 1U, -EBADMSG);
    {
        struct fallback_request candidate = source;
        candidate.kind = ORIGINAL_COMPRESSED;
        candidate.bytes = compressed_original;
        candidate.length = (uint32_t)compressed_bytes;
        candidate.readable_capacity = (uint32_t)compressed_bytes;
        candidate.original_codec = SWAPZ_ZSWAP_IMPORT_LZ4_CODEC;
        candidate.original_codec_version = SWAPZ_ZSWAP_IMPORT_VERSION;
        REQUIRE_STATUS(host_raw_publish(&candidate), -EOPNOTSUPP);
        candidate.original_codec = SWAPZ_ZSWAP_IMPORT_LZO1X_CODEC;
        REQUIRE_STATUS(host_raw_publish(&candidate), -EOPNOTSUPP);
        candidate.original_codec = 0xffU;
        REQUIRE_STATUS(host_raw_publish(&candidate), -EOPNOTSUPP);
    }
    REQUIRE(owner.synthetic_upper_acks == 0U);
    REQUIRE_STATUS(host_raw_publish(&source), 0);
    REQUIRE(owner.maps[1U].valid && owner.maps[1U].raw);
    REQUIRE(owner.maps[1U].extent_blocks == 1U);
    REQUIRE(owner.maps[1U].payload_length == SWAPZ_BLOCK_BYTES);
    REQUIRE(owner.synthetic_upper_acks == 1U);
    REQUIRE(memcmp(owner.memory_lower, owner.preserved_header, SWAPZ_BLOCK_BYTES) == 0);
    REQUIRE(memcmp(owner.memory_lower + SWAPZ_BLOCK_BYTES,
                   original_page, SWAPZ_BLOCK_BYTES) == 0);
    REQUIRE_STATUS(host_raw_read(SWAPZ_BLOCK_BYTES, decoded_page), 0);
    REQUIRE(memcmp(decoded_page, original_page, SWAPZ_BLOCK_BYTES) == 0);
    REQUIRE_STATUS(host_raw_read(SWAPZ_BLOCK_BYTES - 1U, decoded_page), -EIO);
    owner.memory_lower[SWAPZ_BLOCK_BYTES + 9U] ^= 1U;
    REQUIRE_STATUS(host_raw_read(SWAPZ_BLOCK_BYTES, decoded_page), -EBADMSG);
    owner.memory_lower[SWAPZ_BLOCK_BYTES + 9U] ^= 1U;
    owner.maps[1U].raw = 0U;
    REQUIRE_STATUS(host_raw_read(SWAPZ_BLOCK_BYTES, decoded_page), -EUCLEAN);
    owner.maps[1U].raw = 1U;
    REQUIRE_STATUS(host_raw_read(SWAPZ_BLOCK_BYTES, decoded_page), 0);
    REQUIRE(owner.synthetic_upper_acks == 1U);
    printf("PASS round074-agent7 assertions=%u actual_product_RAW=FULL_UNCOMPRESSED_4096 "
           "source_linked_authority=1 codec_confusion_refused=1 "
           "host_receipts_only=1 AUTH=0 PHASE_A=BLOCKED\n", directed_checks);
    return 0;
}
