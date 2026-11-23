/* SPDX-License-Identifier: GPL-2.0-only */
/*
 * Round072 original codec family versus swapz disk/RAW ABI: rootless
 * fail-closed HOST contract test, not original Linux source authentication.
 * The original compressed payload is copied, never recompressed, into a
 * payload-only 4/8/16KiB memory image after a protected 4096-byte header.
 * One ordered owner holds every buffer and descriptor for the entire call.
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
#include "../../../../src/kernel/zswap-import-admission.h"
#include "../../../../src/kernel/authority.h"

_Static_assert(sizeof(struct swapz_map) == 20U, "volatile map ABI changed");
_Static_assert(SWAPZ_CODEC_METADATA_ON_MEDIA == 0U, "in-band disk metadata");
_Static_assert(SWAPZ_ZSWAP_IMPORT_ACTIVE == 0U, "unapproved import activation");
_Static_assert(SWAPZ_ZSWAP_IMPORT_ADMISSION_ACTIVE == 0U, "unapproved admission");
_Static_assert(SWAPZ_DIRECT_HANDOFF_PRODUCTION_ENABLED == 0U, "direct activated");
_Static_assert(SWAPZ_LINUX_SWAP_HEADER_BLOCKS == 1U, "header guard changed");
_Static_assert(SOURCE_MAPPED_AUTHENTICATED == 0, "source auth must stay off");
_Static_assert(DIRECT_COMPRESSED_HANDOFF == 0, "direct handoff must stay off");
_Static_assert(FORCED_RAW_BYPASS == 0, "raw bypass must stay off");

enum record_kind { ORIGINAL_COMPRESSED_OPAQUE, ORDINARY_RAW_4096 };
enum { PHYSICAL_BLOCKS = 5U };
struct source_copy {
    const uint8_t *bytes;
    uint32_t length;
    uint64_t source_epoch;
    uint64_t observed_epoch;
    uint64_t source_identity;
    uint8_t codec;
    uint8_t codec_version;
    uint8_t disk_encoding; /* INVALID means: not a swapz disk encoding. */
    enum record_kind kind;
    bool natural_eviction;
    bool source_lock_held;
    bool immutable_owned_copy;
};
struct volatile_original_tag {
    uint64_t source_epoch;
    uint64_t source_identity;
    uint32_t length;
    uint32_t crc32c;
    uint8_t original_sha256[32];
    uint8_t original_codec;
    uint8_t codec_version;
    enum record_kind kind;
    uint8_t extent_blocks;
    bool immutable_owned;
    bool valid;
};
static uint8_t lower_image[PHYSICAL_BLOCKS * SWAPZ_BLOCK_BYTES];
static uint8_t protected_header[SWAPZ_BLOCK_BYTES];
static struct volatile_original_tag tag;
static unsigned int checks;

#define REQUIRE(check) do { \
    ++checks; \
    if (!(check)) { \
        fprintf(stderr, "FIRST_ERROR line=%d check=%s\n", __LINE__, #check); \
        return 1; \
    } \
} while (0)
#define REQUIRE_STATUS(actual, expected) REQUIRE((actual) == (expected))

static void initialize_protected_header(void)
{
    for (uint32_t index = 0; index < SWAPZ_BLOCK_BYTES; ++index)
        lower_image[index] = (uint8_t)(index * 31U + 7U);
    memcpy(protected_header, lower_image, sizeof(protected_header));
    memset(lower_image + SWAPZ_BLOCK_BYTES, 0xa5,
           sizeof(lower_image) - SWAPZ_BLOCK_BYTES);
    memset(&tag, 0, sizeof(tag));
}

/* Exact source-owned copy only. No encoder/decoder, lower I/O or upper ACK. */
static int store_host(const struct source_copy *source, uint8_t blocks,
                      const uint8_t original_digest[32])
{
    if (!source || !source->bytes || !original_digest)
        return -EINVAL;
    if (!source->natural_eviction)
        return -EPERM;
    if (!source->source_lock_held || !source->immutable_owned_copy)
        return -EPERM;
    if (!source->source_epoch || !source->source_identity ||
        source->source_epoch != source->observed_epoch)
        return -ESTALE;
    if (blocks != 1U && blocks != 2U && blocks != 4U)
        return -EINVAL;
    if (source->kind == ORIGINAL_COMPRESSED_OPAQUE) {
        if (source->codec != SWAPZ_ZSWAP_IMPORT_LZ4_CODEC &&
            source->codec != SWAPZ_ZSWAP_IMPORT_LZO1X_CODEC)
            return -EOPNOTSUPP;
        if (source->codec_version != SWAPZ_ZSWAP_IMPORT_VERSION)
            return -EOPNOTSUPP;
        if (!source->length || source->length > SWAPZ_MAX_COMPRESSED)
            return -EMSGSIZE;
        if (source->disk_encoding != SWAPZ_ENCODING_INVALID)
            return -EOPNOTSUPP;
    } else if (source->kind == ORDINARY_RAW_4096) {
        if (source->length != SWAPZ_BLOCK_BYTES || source->codec != 0U ||
            source->disk_encoding != SWAPZ_ENCODING_INVALID)
            return -EINVAL;
    } else {
        return -EOPNOTSUPP;
    }
    if (source->length > (uint32_t)blocks * SWAPZ_BLOCK_BYTES)
        return -EMSGSIZE;

    /* The physical header is untouched; all metadata stays separate RAM. */
    memset(lower_image + SWAPZ_BLOCK_BYTES, 0, (size_t)blocks * SWAPZ_BLOCK_BYTES);
    memcpy(lower_image + SWAPZ_BLOCK_BYTES, source->bytes, source->length);
    tag = (struct volatile_original_tag){
        .source_epoch = source->source_epoch,
        .source_identity = source->source_identity,
        .length = source->length,
        .crc32c = swapz_crc32c_bytes(source->bytes, source->length),
        .original_codec = source->codec,
        .codec_version = source->codec_version,
        .kind = source->kind,
        .extent_blocks = blocks,
        .immutable_owned = true,
        .valid = true
    };
    memcpy(tag.original_sha256, original_digest, 32U);
    return 0;
}

/*
 * An explicit family bridge. Numeric 2 means original LZO1X in import-codec.h
 * but ZSTD in the obsolete *different* direct-handoff enum. Never cast.
 * There is no original LZO1X direct-handoff decoder registry here.
 */
static int direct_family_compatible(const struct volatile_original_tag *record,
                                    enum swapz_direct_codec direct_codec)
{
    if (record->kind != ORIGINAL_COMPRESSED_OPAQUE)
        return -EOPNOTSUPP;
    if (record->original_codec == SWAPZ_ZSWAP_IMPORT_LZO1X_CODEC)
        return -EOPNOTSUPP;
    if (record->original_codec != SWAPZ_ZSWAP_IMPORT_LZ4_CODEC ||
        direct_codec != SWAPZ_DIRECT_ZSWAP_LZ4)
        return -EOPNOTSUPP;
    return 0;
}

/* Synchronous read-only model. A separate validated RAM tag selects the
 * decoder; lower extent bytes cannot grant codec or source authority. */
static int read_host(uint8_t expected_codec, uint64_t expected_epoch,
                     uint32_t actual_lower_bytes, uint8_t page[SWAPZ_BLOCK_BYTES])
{
    uint8_t scratch[SWAPZ_BLOCK_BYTES];
    struct swapz_zswap_import_record record = {0};
    struct swapz_zswap_import_read_authority authority = {0};
    const uint32_t extent_bytes = (uint32_t)tag.extent_blocks * SWAPZ_BLOCK_BYTES;

    if (!tag.valid || !tag.immutable_owned)
        return -ESTALE;
    if (tag.original_codec != expected_codec ||
        tag.source_epoch != expected_epoch)
        return -ESTALE;
    if (memcmp(lower_image, protected_header, sizeof(protected_header)) != 0)
        return -EIO;
    if (actual_lower_bytes != tag.length)
        return -EIO;
    for (uint32_t offset = tag.length; offset < extent_bytes; ++offset)
        if (lower_image[SWAPZ_BLOCK_BYTES + offset] != 0U)
            return -EBADMSG;
    if (swapz_crc32c_bytes(lower_image + SWAPZ_BLOCK_BYTES,
                           tag.length) != tag.crc32c)
        return -EBADMSG;
    if (tag.kind == ORDINARY_RAW_4096) {
        if (tag.length != SWAPZ_BLOCK_BYTES || tag.original_codec != 0U)
            return -EINVAL;
        uint8_t digest[SHA256_DIGEST_LENGTH];
        if (!SHA256(lower_image + SWAPZ_BLOCK_BYTES, SWAPZ_BLOCK_BYTES, digest) ||
            memcmp(digest, tag.original_sha256, sizeof(digest)) != 0)
            return -EBADMSG;
        memcpy(page, lower_image + SWAPZ_BLOCK_BYTES, SWAPZ_BLOCK_BYTES);
        return 0;
    }
    if (tag.kind != ORIGINAL_COMPRESSED_OPAQUE)
        return -EOPNOTSUPP;
    record.logical_page = 1U;
    record.generation = 1U;
    record.stored_entry_identity = tag.source_identity;
    record.store_generation = tag.source_epoch;
    record.gc_epoch = 1U;
    record.compressed_length = tag.length;
    record.decoded_length = SWAPZ_BLOCK_BYTES;
    record.compressed_crc32c = tag.crc32c;
    record.representation = SWAPZ_ZSWAP_IMPORT_REPRESENTATION;
    record.codec = tag.original_codec;
    record.version = tag.codec_version;
    record.stored_eviction = 1U;
    record.immutable_owned_copy = 1U;
    memcpy(record.original_sha256, tag.original_sha256, 32U);
    authority.logical_page = record.logical_page;
    authority.generation = record.generation;
    authority.stored_entry_identity = record.stored_entry_identity;
    authority.store_generation = record.store_generation;
    authority.gc_epoch = record.gc_epoch;
    authority.actual_lower_read_bytes = actual_lower_bytes;
    authority.mapping_published_after_durable_write = 1U; /* HOST-simulated */
    authority.foreground_write_committed_once = 1U; /* HOST-simulated */
    authority.upper_write_ack_count = 1U; /* HOST-simulated */
    authority.current_owned_ram_session = 1U;
    return swapz_zswap_import_decode(&record, &authority,
                  lower_image + SWAPZ_BLOCK_BYTES, tag.length,
                  scratch, SWAPZ_BLOCK_BYTES, page, SWAPZ_BLOCK_BYTES, NULL);
}

int main(void)
{
    static uint8_t original_page[SWAPZ_BLOCK_BYTES];
    static uint8_t compressed_page[SWAPZ_BLOCK_BYTES];
    static uint8_t read_page[SWAPZ_BLOCK_BYTES];
    uint8_t digest[SHA256_DIGEST_LENGTH];
    struct source_copy source = {0};
    int compressed_length;

    for (uint32_t index = 0; index < SWAPZ_BLOCK_BYTES; ++index)
        original_page[index] = (uint8_t)((index / 128U) % 4U);
    REQUIRE(SHA256(original_page, SWAPZ_BLOCK_BYTES, digest) != NULL);
    compressed_length = LZ4_compress_default((const char *)original_page,
             (char *)compressed_page, (int)SWAPZ_BLOCK_BYTES,
             (int)sizeof(compressed_page));
    REQUIRE(compressed_length > 0 &&
            compressed_length <= (int)SWAPZ_MAX_COMPRESSED);
    source.bytes = compressed_page;
    source.length = (uint32_t)compressed_length;
    source.source_epoch = 7U;
    source.observed_epoch = 7U;
    source.source_identity = 19U;
    source.codec = SWAPZ_ZSWAP_IMPORT_LZ4_CODEC;
    source.codec_version = SWAPZ_ZSWAP_IMPORT_VERSION;
    source.disk_encoding = SWAPZ_ENCODING_INVALID;
    source.kind = ORIGINAL_COMPRESSED_OPAQUE;
    source.natural_eviction = true;
    source.source_lock_held = true;
    source.immutable_owned_copy = true;
    initialize_protected_header();

    for (uint8_t blocks = 1U; blocks <= 4U; blocks *= 2U) {
        REQUIRE_STATUS(store_host(&source, blocks, digest), 0);
        REQUIRE(memcmp(protected_header, lower_image, sizeof(protected_header)) == 0);
        REQUIRE(memcmp(lower_image + SWAPZ_BLOCK_BYTES, compressed_page,
                       source.length) == 0);
        REQUIRE_STATUS(direct_family_compatible(&tag, SWAPZ_DIRECT_ZSWAP_LZ4), 0);
        memset(read_page, 0xc3, sizeof(read_page));
        REQUIRE_STATUS(read_host(source.codec, source.source_epoch,
                                 source.length, read_page), 0);
        REQUIRE(memcmp(read_page, original_page, sizeof(original_page)) == 0);
        REQUIRE_STATUS(read_host(SWAPZ_ZSWAP_IMPORT_LZO1X_CODEC,
                                 source.source_epoch, source.length, read_page), -ESTALE);
        REQUIRE_STATUS(read_host(source.codec, source.source_epoch + 1U,
                                 source.length, read_page), -ESTALE);
        REQUIRE_STATUS(read_host(source.codec, source.source_epoch,
                                 source.length - 1U, read_page), -EIO);
        lower_image[SWAPZ_BLOCK_BYTES + source.length] = 1U;
        REQUIRE_STATUS(read_host(source.codec, source.source_epoch,
                                 source.length, read_page), -EBADMSG);
        lower_image[SWAPZ_BLOCK_BYTES + source.length] = 0U;
        lower_image[SWAPZ_BLOCK_BYTES] ^= 1U;
        REQUIRE_STATUS(read_host(source.codec, source.source_epoch,
                                 source.length, read_page), -EBADMSG);
        lower_image[SWAPZ_BLOCK_BYTES] ^= 1U;
        lower_image[0] ^= 1U;
        REQUIRE_STATUS(read_host(source.codec, source.source_epoch,
                                 source.length, read_page), -EIO);
        lower_image[0] ^= 1U;
        tag.original_sha256[0] ^= 1U;
        REQUIRE_STATUS(read_host(source.codec, source.source_epoch,
                                 source.length, read_page), -EBADMSG);
        tag.original_sha256[0] ^= 1U;
    }

    struct source_copy bad = source;
    bad.natural_eviction = false;
    REQUIRE_STATUS(store_host(&bad, 1U, digest), -EPERM);
    bad = source;
    bad.source_lock_held = false;
    REQUIRE_STATUS(store_host(&bad, 1U, digest), -EPERM);
    bad = source;
    bad.immutable_owned_copy = false;
    REQUIRE_STATUS(store_host(&bad, 1U, digest), -EPERM);
    bad = source;
    bad.observed_epoch++;
    REQUIRE_STATUS(store_host(&bad, 1U, digest), -ESTALE);
    bad = source;
    bad.codec = 0xffU;
    REQUIRE_STATUS(store_host(&bad, 1U, digest), -EOPNOTSUPP);
    bad = source;
    bad.codec_version++;
    REQUIRE_STATUS(store_host(&bad, 1U, digest), -EOPNOTSUPP);
    bad = source;
    bad.disk_encoding = SWAPZ_ENCODING_LZ4;
    REQUIRE_STATUS(store_host(&bad, 1U, digest), -EOPNOTSUPP);
    bad.disk_encoding = SWAPZ_ENCODING_DELTA64;
    REQUIRE_STATUS(store_host(&bad, 1U, digest), -EOPNOTSUPP);
    bad.disk_encoding = SWAPZ_ENCODING_DELTA64_SHUF8;
    REQUIRE_STATUS(store_host(&bad, 1U, digest), -EOPNOTSUPP);
    bad = source;
    bad.length = SWAPZ_MAX_COMPRESSED + 1U;
    REQUIRE_STATUS(store_host(&bad, 1U, digest), -EMSGSIZE);

    /* LZO1X is a distinct owned opaque source, not ZSTD or swapz delta64. */
    bad = source;
    bad.codec = SWAPZ_ZSWAP_IMPORT_LZO1X_CODEC;
    REQUIRE_STATUS(store_host(&bad, 1U, digest), 0);
    REQUIRE(memcmp(lower_image + SWAPZ_BLOCK_BYTES, compressed_page,
                   source.length) == 0);
    REQUIRE_STATUS(direct_family_compatible(&tag, SWAPZ_DIRECT_ZSWAP_ZSTD),
                   -EOPNOTSUPP);
    REQUIRE_STATUS(read_host(bad.codec, bad.source_epoch,
                             bad.length, read_page), -EOPNOTSUPP);

    /* The ordinary 4096 path always stores and reads UNCOMPRESSED originals. */
    bad = source;
    bad.bytes = original_page;
    bad.length = SWAPZ_BLOCK_BYTES;
    bad.codec = 0U;
    bad.kind = ORDINARY_RAW_4096;
    REQUIRE_STATUS(store_host(&bad, 1U, digest), 0);
    memset(read_page, 0xc3, sizeof(read_page));
    REQUIRE_STATUS(read_host(0U, bad.source_epoch, SWAPZ_BLOCK_BYTES, read_page), 0);
    REQUIRE(memcmp(read_page, original_page, sizeof(original_page)) == 0);
    REQUIRE_STATUS(direct_family_compatible(&tag, SWAPZ_DIRECT_ZSWAP_LZ4),
                   -EOPNOTSUPP);
    bad.length = SWAPZ_BLOCK_BYTES - 1U;
    REQUIRE_STATUS(store_host(&bad, 1U, digest), -EINVAL);
    bad.length = SWAPZ_BLOCK_BYTES;
    bad.codec = SWAPZ_ZSWAP_IMPORT_LZ4_CODEC;
    REQUIRE_STATUS(store_host(&bad, 1U, digest), -EINVAL);
    REQUIRE_STATUS(swapz_zswap_admission_try_live(NULL), -EOPNOTSUPP);
    REQUIRE(memcmp(lower_image, protected_header, sizeof(protected_header)) == 0);
    printf("PASS directed=%u extents=4,8,16KiB original_lz4=decoded_4096 "
           "original_lzo=opaque_unsupported RAW_4096=FULL_UNCOMPRESSED "
           "AUTH=0 PHASE_A=BLOCKED no_recompression=1\n", checks);
    return 0;
}
