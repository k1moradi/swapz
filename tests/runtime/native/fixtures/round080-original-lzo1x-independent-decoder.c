/* SPDX-License-Identifier: GPL-2.0-only */
/*
 * Round080 Agent7: HOST-ONLY actual original LZO1X positive decoder witness.
 * lzo1x_1_compress is from system liblzo2; the decoder is compiled directly
 * from pristine torvalds/linux pin c339f4010dea8b0d754f84ace70cd1b089878ef8.
 * The real dormant product import decoder + owner.c are linked, not copied.
 *
 * All asserted "selected" identities are HOST-SIMULATED and untrusted.
 * This fixture NEVER proves live original Linux STORED-source authentication,
 * physical FUA, once-only upper bio_endio, selected DM, or activation.
 */
#include <errno.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <pthread.h>
#include <linux/lzo.h>
#include <openssl/sha.h>

#define SOURCE_MAPPED_AUTHENTICATED 0
#define DIRECT_COMPRESSED_HANDOFF 0
#define FORCED_RAW_BYPASS 0
#include "../../../../src/kernel/zswap-import-decoder-owner.h"
#include "../../../../src/kernel/zswap-direct-handoff.h"
#include "../../../../src/kernel/authority.h"

_Static_assert(SWAPZ_ZSWAP_IMPORT_ACTIVE == 0U, "original import disabled");
_Static_assert(SWAPZ_ZSWAP_IMPORT_LZO1X_CODEC == 2U, "original LZO1X codec tag");
_Static_assert(SWAPZ_DIRECT_ZSWAP_ZSTD == 2, "direct tag2 is ZSTD not LZO");
_Static_assert(SWAPZ_ZSWAP_IMPORT_LZO1X_VERSION == 1U, "original codec version");
_Static_assert(SWAPZ_DIRECT_HANDOFF_PRODUCTION_ENABLED == 0U, "handoff disabled");
_Static_assert(SWAPZ_BLOCK_BYTES == 4096U, "original decoded page size");
_Static_assert(SWAPZ_MAX_COMPRESSED == 3568U, "dormant bound");
_Static_assert(sizeof(struct swapz_map) == 20U, "volatile map layout");
_Static_assert(SWAPZ_LINUX_SWAP_HEADER_BLOCKS == 1U, "physical header reserve");
_Static_assert(SWAPZ_CODEC_METADATA_ON_MEDIA == 0U, "no metadata on media");
_Static_assert(SOURCE_MAPPED_AUTHENTICATED == 0, "authentication blocked");
_Static_assert(DIRECT_COMPRESSED_HANDOFF == 0, "direct disabled");
_Static_assert(FORCED_RAW_BYPASS == 0, "forced raw disabled");

enum original_source_namespace {
    SOURCE_ORIGINAL_LZO1X,
    SOURCE_DIRECT_UNTYPED,
    SOURCE_SWAPZ_DISK,
};
enum host_representation {
    HOST_ORIGINAL_LZO1X_COMPRESSED,
    HOST_COMPLETE_RAW_UNCOMPRESSED,
};
struct host_original_witness {
    struct swapz_zswap_import_record record;
    struct swapz_zswap_import_read_authority authority;
    enum original_source_namespace codec_namespace;
    enum host_representation representation;
    swapz_u8 direct_handoff_codec;
    swapz_u64 selected_logical_page;
    swapz_u64 selected_generation;
    swapz_u64 selected_record_identity;
    swapz_u64 selected_store_generation;
    swapz_u32 source_readable_capacity;
    swapz_u32 source_copy_length;
    swapz_u32 actual_lower_read_bytes;
    swapz_u8 independent_page_digest[SHA256_DIGEST_LENGTH];
    bool host_selected_source_assertion; /* NOT real original Linux proof */
    bool selected_dm_witness;
    bool owns_original_bytes;
    bool original_decoder_retained;
    bool original_stream_is_unframed;
    bool natural_eviction_only;
    bool original_entry_is_uncompressed;
    bool source_lease_current;
    bool requests_recompression;
    bool requests_second_reclaimer;
};
struct raw_witness {
    enum host_representation representation;
    swapz_u8 codec;
    swapz_u32 logical_length;
    swapz_u32 readable_capacity;
    swapz_u32 actual_lower_read_bytes;
    swapz_u8 independent_page_digest[SHA256_DIGEST_LENGTH];
};
enum {
    HOST_COMPRESSED_CAPACITY = 8192U,
    HOST_LZO_WORK_MEMORY_BYTES = 262144U
};
static swapz_u8 page[SWAPZ_BLOCK_BYTES];
static swapz_u8 compressed[HOST_COMPRESSED_CAPACITY];
static swapz_u8 scratch[SWAPZ_BLOCK_BYTES];
static swapz_u8 output[SWAPZ_BLOCK_BYTES];
static swapz_u8 digest[SHA256_DIGEST_LENGTH];
static uint64_t lzo_workspace[HOST_LZO_WORK_MEMORY_BYTES / sizeof(uint64_t)];
static unsigned int assertions;

#define REQUIRE(condition) do { \
    ++assertions; \
    if (!(condition)) { \
        fprintf(stderr, "FIRST_ERROR line=%d check=%s\n", __LINE__, #condition); \
        return 1; \
    } \
} while (0)
#define REQUIRE_RESULT(actual, expected) REQUIRE((actual) == (expected))

/*
 * An explicit, TEST-ONLY original namespace boundary. The numeric value2
 * cannot be copied from direct ZSTD2 into this separately original LZO1X2
 * domain, nor can the actual decoder owner substitute for source authority.
 * The host metadata here has no live XArray or verified selected DM source.
 */
static int host_original_read(
    const struct host_original_witness *source,
    const struct swapz_zswap_import_decoder_lease *original_lease,
    const swapz_u8 *immutable_compressed_bytes,
    swapz_u8 *private_scratch,
    swapz_u8 *upper_page)
{
    if (!source || !original_lease || !immutable_compressed_bytes ||
        !private_scratch || !upper_page)
        return -EINVAL;
    if (source->codec_namespace != SOURCE_ORIGINAL_LZO1X)
        return -EPROTO;
    if (source->representation != HOST_ORIGINAL_LZO1X_COMPRESSED)
        return -EPROTO;
    if (source->direct_handoff_codec != SWAPZ_DIRECT_CODEC_UNKNOWN)
        return -EPROTO;
    if (!source->host_selected_source_assertion)
        return -EPERM;
    if (!source->selected_dm_witness)
        return -ENODEV;
    if (!source->owns_original_bytes)
        return -EPERM;
    if (!source->original_decoder_retained)
        return -ESTALE;
    if (!source->original_stream_is_unframed)
        return -EPROTO;
    if (!source->natural_eviction_only)
        return -EPERM;
    if (source->original_entry_is_uncompressed)
        return -EOPNOTSUPP;
    if (!source->source_lease_current)
        return -ESTALE;
    if (source->requests_recompression)
        return -EOPNOTSUPP;
    if (source->requests_second_reclaimer)
        return -EOPNOTSUPP;
    if (source->record.codec != SWAPZ_ZSWAP_IMPORT_LZO1X_CODEC)
        return -EPROTO;
    if (source->record.version != SWAPZ_ZSWAP_IMPORT_LZO1X_VERSION)
        return -EPROTO;
    if (!original_lease->owner)
        return -ESTALE;
    if (source->selected_logical_page != source->record.logical_page)
        return -ESTALE;
    if (source->selected_generation != source->record.generation)
        return -ESTALE;
    if (source->selected_record_identity != source->record.stored_entry_identity)
        return -ESTALE;
    if (source->selected_store_generation != source->record.store_generation)
        return -ESTALE;
    if (source->source_readable_capacity < source->record.compressed_length)
        return -EMSGSIZE;
    if (source->source_copy_length != source->record.compressed_length)
        return -EMSGSIZE;
    if (source->actual_lower_read_bytes != source->record.compressed_length)
        return -ENODATA;
    if (memcmp(source->independent_page_digest, source->record.original_sha256,
               SHA256_DIGEST_LENGTH) != 0)
        return -EBADMSG;
    return swapz_zswap_import_decoder_owner_decode(
        original_lease, &source->record, &source->authority,
        immutable_compressed_bytes, source->source_readable_capacity,
        private_scratch, SWAPZ_BLOCK_BYTES, upper_page,
        SWAPZ_BLOCK_BYTES, page);
}

/* RAW_4096 requires a full ORIGINAL UNCOMPRESSED 4096-byte input.
 * Never treat an original compressed stream as a conventional RAW page.
 */
static int host_raw_page(const struct raw_witness *source,
                         const swapz_u8 *original_uncompressed,
                         swapz_u8 upper_page[SWAPZ_BLOCK_BYTES])
{
    swapz_u8 actual_digest[SHA256_DIGEST_LENGTH];
    if (!source || !original_uncompressed || !upper_page)
        return -EINVAL;
    if (source->representation != HOST_COMPLETE_RAW_UNCOMPRESSED)
        return -EOPNOTSUPP;
    if (source->codec != 0U)
        return -EOPNOTSUPP;
    if (source->logical_length != SWAPZ_BLOCK_BYTES)
        return -EMSGSIZE;
    if (source->readable_capacity < SWAPZ_BLOCK_BYTES)
        return -EMSGSIZE;
    if (source->actual_lower_read_bytes != SWAPZ_BLOCK_BYTES)
        return -EIO;
    if (!SHA256(original_uncompressed, SWAPZ_BLOCK_BYTES, actual_digest))
        return -EIO;
    if (memcmp(source->independent_page_digest, actual_digest,
               SHA256_DIGEST_LENGTH) != 0)
        return -EBADMSG;
    memcpy(upper_page, original_uncompressed, SWAPZ_BLOCK_BYTES);
    return 0;
}

int main(void)
{
    struct swapz_zswap_import_decoder_owner decoder_owner = {0};
    struct swapz_zswap_import_decoder_lease original_lease = {0};
    struct swapz_zswap_import_decoder_lease duplicate_lease = {0};
    struct host_original_witness source = {0};
    struct raw_witness raw = {0};
    size_t compressed_bytes = sizeof(compressed);
    int compressed_status;
    uint32_t offset;

    /* Compress the genuine original 4096 byte pattern using LZO1X_1.
     * The actual decoder implementation is the PINNED Linux C object
     * linked through the unchanged product original import function.
     */
    for (offset = 0U; offset < SWAPZ_BLOCK_BYTES; ++offset)
        page[offset] = (swapz_u8)((offset / 32U) % 9U + (offset / 1024U));
    REQUIRE(SHA256(page, SWAPZ_BLOCK_BYTES, digest) != NULL);
    compressed_status = lzo1x_1_compress(page, SWAPZ_BLOCK_BYTES,
        compressed, &compressed_bytes, lzo_workspace);
    REQUIRE_RESULT(compressed_status, LZO_E_OK);
    REQUIRE(compressed_bytes > 0U && compressed_bytes <= SWAPZ_MAX_COMPRESSED);
    REQUIRE(compressed_bytes < SWAPZ_BLOCK_BYTES);
    REQUIRE_RESULT(swapz_zswap_import_decoder_owner_init(
        &decoder_owner, SWAPZ_ZSWAP_IMPORT_LZO1X_CODEC,
        SWAPZ_ZSWAP_IMPORT_LZO1X_VERSION), 0);
    REQUIRE_RESULT(swapz_zswap_import_decoder_owner_get(
        &decoder_owner, &original_lease), 0);
    REQUIRE_RESULT(swapz_zswap_import_decoder_owner_get(
        &decoder_owner, &original_lease), -EBUSY);

    source.record.logical_page = 101U;
    source.record.generation = 103U;
    source.record.stored_entry_identity = 107U;
    source.record.store_generation = 109U;
    source.record.gc_epoch = 113U;
    source.record.compressed_length = (swapz_u32)compressed_bytes;
    source.record.decoded_length = SWAPZ_BLOCK_BYTES;
    source.record.compressed_crc32c =
        swapz_crc32c_bytes(compressed, (swapz_u32)compressed_bytes);
    source.record.representation = SWAPZ_ZSWAP_IMPORT_REPRESENTATION;
    source.record.codec = SWAPZ_ZSWAP_IMPORT_LZO1X_CODEC;
    source.record.version = SWAPZ_ZSWAP_IMPORT_LZO1X_VERSION;
    source.record.stored_eviction = 1U;
    source.record.immutable_owned_copy = 1U;
    memcpy(source.record.original_sha256, digest, sizeof(digest));
    source.authority.logical_page = source.record.logical_page;
    source.authority.generation = source.record.generation;
    source.authority.stored_entry_identity = source.record.stored_entry_identity;
    source.authority.store_generation = source.record.store_generation;
    source.authority.gc_epoch = source.record.gc_epoch;
    source.authority.actual_lower_read_bytes = (swapz_u32)compressed_bytes;
    source.authority.mapping_published_after_durable_write = 1U;
    source.authority.foreground_write_committed_once = 1U;
    source.authority.upper_write_ack_count = 1U;
    source.authority.current_owned_ram_session = 1U;

    source.codec_namespace = SOURCE_ORIGINAL_LZO1X;
    source.representation = HOST_ORIGINAL_LZO1X_COMPRESSED;
    source.selected_logical_page = source.record.logical_page;
    source.selected_generation = source.record.generation;
    source.selected_record_identity = source.record.stored_entry_identity;
    source.selected_store_generation = source.record.store_generation;
    source.source_readable_capacity = (swapz_u32)compressed_bytes;
    source.source_copy_length = (swapz_u32)compressed_bytes;
    source.actual_lower_read_bytes = (swapz_u32)compressed_bytes;
    memcpy(source.independent_page_digest, digest, sizeof(digest));
    source.host_selected_source_assertion = true;
    source.selected_dm_witness = true;
    source.owns_original_bytes = true;
    source.original_decoder_retained = true;
    source.original_stream_is_unframed = true;
    source.natural_eviction_only = true;
    source.source_lease_current = true;

    /* Real product positive: original LZO tag2 + real retained decoder
     * owner + independent original digest + pinned Linux decompressor.
     */
    memset(output, 0x7b, sizeof(output));
    REQUIRE_RESULT(host_original_read(&source, &original_lease, compressed,
        scratch, output), 0);
    REQUIRE(memcmp(output, page, SWAPZ_BLOCK_BYTES) == 0);

#define EXPECT_SOURCE_REJECT(change, error) do { \
        struct host_original_witness candidate = source; \
        memset(output, 0x7b, sizeof(output)); \
        change; \
        REQUIRE_RESULT(host_original_read(&candidate, &original_lease, \
            compressed, scratch, output), (error)); \
        REQUIRE(output[0] == 0x7bU && output[SWAPZ_BLOCK_BYTES - 1U] == 0x7bU); \
    } while (0)
    EXPECT_SOURCE_REJECT(candidate.codec_namespace = SOURCE_DIRECT_UNTYPED, -EPROTO);
    EXPECT_SOURCE_REJECT(candidate.codec_namespace = SOURCE_SWAPZ_DISK, -EPROTO);
    EXPECT_SOURCE_REJECT(candidate.representation = HOST_COMPLETE_RAW_UNCOMPRESSED, -EPROTO);
    EXPECT_SOURCE_REJECT(candidate.direct_handoff_codec = SWAPZ_DIRECT_ZSWAP_ZSTD, -EPROTO);
    EXPECT_SOURCE_REJECT(candidate.host_selected_source_assertion = false, -EPERM);
    EXPECT_SOURCE_REJECT(candidate.selected_dm_witness = false, -ENODEV);
    EXPECT_SOURCE_REJECT(candidate.owns_original_bytes = false, -EPERM);
    EXPECT_SOURCE_REJECT(candidate.original_decoder_retained = false, -ESTALE);
    EXPECT_SOURCE_REJECT(candidate.original_stream_is_unframed = false, -EPROTO);
    EXPECT_SOURCE_REJECT(candidate.natural_eviction_only = false, -EPERM);
    EXPECT_SOURCE_REJECT(candidate.original_entry_is_uncompressed = true, -EOPNOTSUPP);
    EXPECT_SOURCE_REJECT(candidate.source_lease_current = false, -ESTALE);
    EXPECT_SOURCE_REJECT(candidate.requests_recompression = true, -EOPNOTSUPP);
    EXPECT_SOURCE_REJECT(candidate.requests_second_reclaimer = true, -EOPNOTSUPP);
    EXPECT_SOURCE_REJECT(candidate.record.codec = SWAPZ_ZSWAP_IMPORT_LZ4_CODEC, -EPROTO);
    EXPECT_SOURCE_REJECT(candidate.record.version = 0xffU, -EPROTO);
    EXPECT_SOURCE_REJECT(candidate.selected_logical_page++, -ESTALE);
    EXPECT_SOURCE_REJECT(candidate.selected_generation++, -ESTALE);
    EXPECT_SOURCE_REJECT(candidate.selected_record_identity++, -ESTALE);
    EXPECT_SOURCE_REJECT(candidate.selected_store_generation++, -ESTALE);
    EXPECT_SOURCE_REJECT(candidate.source_readable_capacity--, -EMSGSIZE);
    EXPECT_SOURCE_REJECT(candidate.source_copy_length--, -EMSGSIZE);
    EXPECT_SOURCE_REJECT(candidate.actual_lower_read_bytes--, -ENODATA);
    EXPECT_SOURCE_REJECT(candidate.independent_page_digest[0] ^= 1U, -EBADMSG);

    /* A real decoder owner never infers original codec2 from direct ZSTD2.
     * Product guards decode and authority fields even if HOST flags claim
     * source validity. No failed test can alter the upper 4096-byte buffer.
     */
#define EXPECT_PRODUCT_REJECT(change, error) do { \
        struct host_original_witness candidate = source; \
        change; \
        memset(output, 0x7b, sizeof(output)); \
        REQUIRE_RESULT(swapz_zswap_import_decoder_owner_decode( \
            &original_lease, &candidate.record, &candidate.authority, \
            compressed, (swapz_u32)compressed_bytes, scratch, \
            SWAPZ_BLOCK_BYTES, output, SWAPZ_BLOCK_BYTES, page), (error)); \
        REQUIRE(output[0] == 0x7bU && output[SWAPZ_BLOCK_BYTES - 1U] == 0x7bU); \
    } while (0)
    EXPECT_PRODUCT_REJECT(candidate.record.codec = SWAPZ_ZSWAP_IMPORT_LZ4_CODEC, -EOPNOTSUPP);
    EXPECT_PRODUCT_REJECT(candidate.record.version = 0xffU, -EOPNOTSUPP);
    EXPECT_PRODUCT_REJECT(candidate.record.representation = 0xffU, -EOPNOTSUPP);
    EXPECT_PRODUCT_REJECT(candidate.record.stored_eviction = 0U, -EOPNOTSUPP);
    EXPECT_PRODUCT_REJECT(candidate.record.immutable_owned_copy = 0U, -EOPNOTSUPP);
    EXPECT_PRODUCT_REJECT(candidate.record.dictionary_id = 1U, -EOPNOTSUPP);
    EXPECT_PRODUCT_REJECT(candidate.record.compressed_length = SWAPZ_MAX_COMPRESSED + 1U, -EMSGSIZE);
    EXPECT_PRODUCT_REJECT(candidate.record.compressed_length = SWAPZ_BLOCK_BYTES, -EMSGSIZE);
    EXPECT_PRODUCT_REJECT(candidate.record.decoded_length = SWAPZ_BLOCK_BYTES - 1U, -EMSGSIZE);
    EXPECT_PRODUCT_REJECT(candidate.record.compressed_crc32c ^= 1U, -EBADMSG);
    EXPECT_PRODUCT_REJECT(candidate.record.original_sha256[0] ^= 1U, -EBADMSG);
    EXPECT_PRODUCT_REJECT(candidate.authority.generation++, -ESTALE);
    EXPECT_PRODUCT_REJECT(candidate.authority.stored_entry_identity++, -ESTALE);
    EXPECT_PRODUCT_REJECT(candidate.authority.store_generation++, -ESTALE);
    EXPECT_PRODUCT_REJECT(candidate.authority.gc_epoch++, -ESTALE);
    EXPECT_PRODUCT_REJECT(candidate.authority.actual_lower_read_bytes--, -EIO);
    EXPECT_PRODUCT_REJECT(candidate.authority.lower_read_error = -EIO, -EIO);
    EXPECT_PRODUCT_REJECT(candidate.authority.upper_write_ack_count = 2U, -ESTALE);
    EXPECT_PRODUCT_REJECT(candidate.authority.current_owned_ram_session = 0U, -ESTALE);
    EXPECT_PRODUCT_REJECT(candidate.authority.teardown_started = 1U, -ESTALE);
    EXPECT_PRODUCT_REJECT(candidate.authority.upper_read_ack_count = 1U, -ESTALE);
    {
        struct swapz_zswap_import_record record = source.record;
        struct swapz_zswap_import_read_authority authority = source.authority;
        memset(output, 0x7b, sizeof(output));
        REQUIRE_RESULT(swapz_zswap_import_decoder_owner_decode(
            &original_lease, &record, &authority, compressed,
            (swapz_u32)compressed_bytes - 1U, scratch,
            SWAPZ_BLOCK_BYTES, output, SWAPZ_BLOCK_BYTES, page), -EMSGSIZE);
        REQUIRE(output[0] == 0x7bU);
    }
    {
        struct swapz_zswap_import_record record = source.record;
        struct swapz_zswap_import_read_authority authority = source.authority;
        swapz_u8 extra[HOST_COMPRESSED_CAPACITY] = {0};
        memcpy(extra, compressed, compressed_bytes);
        extra[compressed_bytes] = 0x42U;
        record.compressed_length++;
        record.compressed_crc32c = swapz_crc32c_bytes(
            extra, record.compressed_length);
        authority.actual_lower_read_bytes++;
        memset(output, 0x7b, sizeof(output));
        REQUIRE_RESULT(swapz_zswap_import_decoder_owner_decode(
            &original_lease, &record, &authority, extra,
            record.compressed_length, scratch, SWAPZ_BLOCK_BYTES,
            output, SWAPZ_BLOCK_BYTES, page), -EBADMSG);
        REQUIRE(output[0] == 0x7bU);
    }
    {
        struct swapz_zswap_import_record record = source.record;
        struct swapz_zswap_import_read_authority authority = source.authority;
        memset(output, 0x7b, sizeof(output));
        REQUIRE_RESULT(swapz_zswap_import_decoder_owner_decode(
            &original_lease, &record, &authority, compressed,
            (swapz_u32)compressed_bytes, output, SWAPZ_BLOCK_BYTES,
            output, SWAPZ_BLOCK_BYTES, page), -EINVAL);
        REQUIRE(output[0] == 0x7bU);
    }

    /* HOST model of the conventional raw boundary, independently SHA-bound
     * to the complete ORIGINAL uncompressed page, never original LZO bytes.
     */
    raw.representation = HOST_COMPLETE_RAW_UNCOMPRESSED;
    raw.logical_length = SWAPZ_BLOCK_BYTES;
    raw.readable_capacity = SWAPZ_BLOCK_BYTES;
    raw.actual_lower_read_bytes = SWAPZ_BLOCK_BYTES;
    memcpy(raw.independent_page_digest, digest, sizeof(digest));
#define EXPECT_RAW_REJECT(change, error) do { \
        struct raw_witness candidate = raw; \
        change; \
        memset(output, 0x7b, sizeof(output)); \
        REQUIRE_RESULT(host_raw_page(&candidate, page, output), (error)); \
        REQUIRE(output[0] == 0x7bU && output[SWAPZ_BLOCK_BYTES - 1U] == 0x7bU); \
    } while (0)
    EXPECT_RAW_REJECT(candidate.representation = HOST_ORIGINAL_LZO1X_COMPRESSED, -EOPNOTSUPP);
    EXPECT_RAW_REJECT(candidate.codec = SWAPZ_ZSWAP_IMPORT_LZO1X_CODEC, -EOPNOTSUPP);
    EXPECT_RAW_REJECT(candidate.logical_length = SWAPZ_BLOCK_BYTES - 1U, -EMSGSIZE);
    EXPECT_RAW_REJECT(candidate.readable_capacity = SWAPZ_BLOCK_BYTES - 1U, -EMSGSIZE);
    EXPECT_RAW_REJECT(candidate.actual_lower_read_bytes = SWAPZ_BLOCK_BYTES - 1U, -EIO);
    EXPECT_RAW_REJECT(candidate.independent_page_digest[0] ^= 1U, -EBADMSG);
    {
        struct raw_witness compressed_alias = raw;
        compressed_alias.representation = HOST_ORIGINAL_LZO1X_COMPRESSED;
        compressed_alias.codec = SWAPZ_ZSWAP_IMPORT_LZO1X_CODEC;
        compressed_alias.logical_length = (swapz_u32)compressed_bytes;
        compressed_alias.readable_capacity = (swapz_u32)compressed_bytes;
        compressed_alias.actual_lower_read_bytes = (swapz_u32)compressed_bytes;
        memset(output, 0x7b, sizeof(output));
        REQUIRE_RESULT(host_raw_page(&compressed_alias, compressed, output),
                       -EOPNOTSUPP);
        REQUIRE(output[0] == 0x7bU);
    }
    REQUIRE_RESULT(host_raw_page(&raw, page, output), 0);
    REQUIRE(memcmp(output, page, SWAPZ_BLOCK_BYTES) == 0);

    REQUIRE_RESULT(swapz_zswap_import_decoder_owner_get(
        &decoder_owner, &duplicate_lease), 0);
    REQUIRE_RESULT(swapz_zswap_import_decoder_owner_put(&duplicate_lease), 0);
    REQUIRE_RESULT(swapz_zswap_import_decoder_owner_put(&duplicate_lease), -EALREADY);
    REQUIRE_RESULT(swapz_zswap_import_decoder_owner_put(&original_lease), 0);
    REQUIRE_RESULT(swapz_zswap_import_decoder_owner_put(&original_lease), -EALREADY);
    REQUIRE_RESULT(swapz_zswap_import_decoder_owner_close_and_drain(
        &decoder_owner), 0);
    REQUIRE_RESULT(swapz_zswap_import_decoder_owner_get(
        &decoder_owner, &original_lease), -ESHUTDOWN);
    REQUIRE_RESULT(swapz_zswap_import_decoder_owner_decode(
        &original_lease, &source.record, &source.authority, compressed,
        (swapz_u32)compressed_bytes, scratch, SWAPZ_BLOCK_BYTES,
        output, SWAPZ_BLOCK_BYTES, page), -EINVAL);
    REQUIRE_RESULT(pthread_cond_destroy(&decoder_owner.drained), 0);
    REQUIRE_RESULT(pthread_mutex_destroy(&decoder_owner.lock), 0);

    printf("PASS round080-agent7 assertions=%u "
           "original_lzo1x=REAL_PINNED_LINUX_DECOMPRESS_4096 "
           "original_codec2=LZO1X direct_codec2=ZSTD "
           "original_lease=RETAINED_AND_DRAINED "
           "raw4096=FULL_ORIGINAL_UNCOMPRESSED "
           "AUTH=0 PHASE_A=BLOCKED\n", assertions);
    return 0;
}
