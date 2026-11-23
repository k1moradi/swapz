/* SPDX-License-Identifier: GPL-2.0-only */
/*
 * Round078 Agent9 — source-linked HOST ONLY original zswap length admission.
 * The upstream source-verified expressions are inserted into this file at
 * two unique markers by the Python verifier. They are executable C, not
 * regex-only acceptance tests. All product headers are current source copies.
 *
 * The original Linux compressed stream is NOT available in this host test.
 * A real raw-block LZ4 stream independently tests the DORMANT import decode.
 * Admission-length fixtures made of arbitrary bytes are NEVER claimed to be
 * valid compressed LZO1X/LZ4 streams; LZO1X decoding is NOT_COVERED here.
 */
#include <errno.h>
#include <limits.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <lz4.h>
#include <openssl/sha.h>

#define SWAPZ_ZSWAP_IMPORT_HOST_TEST 1
#define SWAPZ_ZSWAP_ADMISSION_HOST_TEST 1
#include "zswap-import-admission.h"
#include "superblock.h"
#include "authority.h"

_Static_assert(SWAPZ_BLOCK_BYTES == 4096U, "complete original page");
_Static_assert(SWAPZ_MAX_BLOCKS == 4U, "data-only extent classes");
_Static_assert(SWAPZ_CODEC_METADATA_ON_MEDIA == 0U, "metadata is RAM only");
_Static_assert(SWAPZ_SUPERBLOCK_BYTES == 4096U, "protected Linux page");
_Static_assert(SWAPZ_LINUX_SWAP_UUID_OFFSET == 1036U, "physical UUID");
_Static_assert(SWAPZ_ZSWAP_IMPORT_ACTIVE == 0U, "import remains inactive");
_Static_assert(SWAPZ_ZSWAP_IMPORT_ADMISSION_ACTIVE == 0U, "no live bridge");
_Static_assert(SWAPZ_MAX_COMPRESSED < SWAPZ_BLOCK_BYTES, "separate limits");
_Static_assert(sizeof(struct swapz_map) == 20U, "exact volatile map shape");

#define PAGE_SIZE SWAPZ_BLOCK_BYTES
#define ORIGINAL_ZSWAP_REJECT_CONDITION \
    (/* ROUND078_UPSTREAM_COMPRESSION_CONDITION */)
#define ORIGINAL_ZSWAP_RAW_READ_CONDITION \
    (/* ROUND078_UPSTREAM_RAW_READ_CONDITION */)

#define CHECK(condition, label) do { \
    if (!(condition)) { \
        fprintf(stderr, "ROUND078_LENGTH_SEMANTIC_FAILURE case=%s line=%d\n", \
                (label), __LINE__); \
        return 3; \
    } \
} while (0)

enum original_stored_kind {
    ORIGINAL_INVALID = 0,
    ORIGINAL_COMPRESSED,
    ORIGINAL_UNCOMPRESSED_4096
};

struct original_stored_entry {
    unsigned int length;
};

static enum original_stored_kind original_source_classify(
        unsigned int dlen, int comp_ret, bool writeback_enabled)
{
    if (ORIGINAL_ZSWAP_REJECT_CONDITION) {
        if (!writeback_enabled)
            return ORIGINAL_INVALID;
        return ORIGINAL_UNCOMPRESSED_4096;
    }
    return ORIGINAL_COMPRESSED;
}

static bool original_source_read_is_uncompressed(unsigned int length)
{
    struct original_stored_entry stored_entry = {.length = length};
    const struct original_stored_entry *entry = &stored_entry;

    return ORIGINAL_ZSWAP_RAW_READ_CONDITION;
}

/* This is an explicit HOST fallback contract, not an active DM write path.
 * Caller must independently retain the complete original uncompressed folio.
 * No zswap compressed length, codec inference or borrowed source can authorize
 * RAW_4096. output and input are both owned until this synchronous copy ends.
 */
static int modeled_full_uncompressed_fallback(
        const unsigned char *original_folio, unsigned int available_bytes,
        bool source_owned, const unsigned char expected_sha256[32],
        unsigned char output[4096])
{
    unsigned char digest[32];
    if (!source_owned || !original_folio || available_bytes != PAGE_SIZE ||
        !expected_sha256 || !output)
        return -ESTALE;
    if (!SHA256(original_folio, PAGE_SIZE, digest) ||
        memcmp(digest, expected_sha256, sizeof(digest)) != 0)
        return -EBADMSG;
    memcpy(output, original_folio, PAGE_SIZE);
    return 0;
}

static void make_record(struct swapz_zswap_import_record *record,
                        const unsigned char *original, const unsigned char *bytes,
                        unsigned int compressed_length)
{
    *record = (struct swapz_zswap_import_record) {
        .logical_page = 4U,
        .generation = 6U,
        .stored_entry_identity = 9U,
        .store_generation = 11U,
        .gc_epoch = 13U,
        .compressed_length = compressed_length,
        .decoded_length = PAGE_SIZE,
        .representation = SWAPZ_ZSWAP_IMPORT_REPRESENTATION,
        .codec = SWAPZ_ZSWAP_IMPORT_LZ4_CODEC,
        .version = SWAPZ_ZSWAP_IMPORT_VERSION,
        .dictionary_id = 0U,
        .stored_eviction = 1U,
        .immutable_owned_copy = 1U,
    };
    if (compressed_length <= PAGE_SIZE + 1U)
        record->compressed_crc32c = swapz_crc32c_bytes(bytes, compressed_length);
    (void)SHA256(original, PAGE_SIZE, record->original_sha256);
}

static struct swapz_zswap_admission_mapping make_mapping(void)
{
    return (struct swapz_zswap_admission_mapping) {
        .source_swap_slot = 4U,
        .source_store_generation = 11U,
        .source_stored_entry_identity = 9U,
        .dm_logical_page = 4U,
        .dm_generation = 6U,
        .dm_gc_epoch = 13U,
        .physical_extent_bytes = PAGE_SIZE,
        .compressed_payload_offset = 0U,
        .post_header_extent_authorized = 1U,
        .deterministic_zero_padding = 1U,
        .source_stored_eviction_verified = 1U,
        .compressed_source_owned_copy = 1U,
        .original_sha256_from_store = 1U,
        .mock_bridge_only = 1U,
    };
}

static int mock_stage(const struct swapz_zswap_import_record *record,
                      struct swapz_zswap_admission_mapping mapping,
                      const unsigned char *owned_bytes,
                      unsigned int capacity,
                      struct swapz_zswap_admission_transaction *transaction)
{
    memset(transaction, 0, sizeof(*transaction));
    return swapz_zswap_admission_begin_mock(transaction, &mapping, record,
                                           owned_bytes, capacity);
}

static struct swapz_zswap_import_read_authority make_read_authority(
        const struct swapz_zswap_import_record *record)
{
    return (struct swapz_zswap_import_read_authority) {
        .logical_page = record->logical_page,
        .generation = record->generation,
        .stored_entry_identity = record->stored_entry_identity,
        .store_generation = record->store_generation,
        .gc_epoch = record->gc_epoch,
        .actual_lower_read_bytes = record->compressed_length,
        .mapping_published_after_durable_write = 1U,
        .foreground_write_committed_once = 1U,
        .upper_write_ack_count = 1U,
        .current_owned_ram_session = 1U,
    };
}

static void make_original(unsigned char original[4096])
{
    memset(original, 'A', PAGE_SIZE);
    for (unsigned int index = 0U; index < 32U; ++index)
        original[index * 128U] = (unsigned char)(index + 1U);
    original[PAGE_SIZE - 1U] = 0x71U;
}

int main(void)
{
    unsigned char original[4096], compressed[4097], scratch[4096], output[4096];
    unsigned char expected_sha256[32], corrupted_sha256[32];
    unsigned char physical[4096U + 16384U], original_header[4096];
    struct swapz_zswap_import_record record, altered_record;
    struct swapz_zswap_import_read_authority read_authority, altered_read;
    struct swapz_zswap_admission_transaction transaction;
    struct swapz_zswap_admission_mapping mapping;
    int compressed_length;
    const unsigned int permitted_lengths[] = {1U, 3567U, 3568U};
    const unsigned int forbidden_lengths[] = {0U, 3569U, 4095U,
                                               4096U, 4097U, UINT_MAX};

    make_original(original);
    (void)SHA256(original, PAGE_SIZE, expected_sha256);
    memset(compressed, 0x53, sizeof(compressed));
    compressed_length = LZ4_compress_default((const char *)original,
                                            (char *)compressed, (int)PAGE_SIZE,
                                            (int)sizeof(compressed));
    CHECK(compressed_length > 0 &&
          (unsigned int)compressed_length <= SWAPZ_MAX_COMPRESSED,
          "genuine-lz4-stream-within-current-product-limit");
    mapping = make_mapping();

    /* The exact upstream C expression controls the simulated shape, NOT
     * any synthetic 3568 ceiling: lengths 3569..4095 are valid by bounds.
     * It says nothing about their frequency under real codecs/real data.
     */
    CHECK(original_source_classify(1U, 0, true) == ORIGINAL_COMPRESSED,
          "upstream-min-compressed");
    CHECK(original_source_classify(3568U, 0, true) == ORIGINAL_COMPRESSED,
          "upstream-product-edge-compressed");
    CHECK(original_source_classify(3569U, 0, true) == ORIGINAL_COMPRESSED,
          "upstream-above-product-limit-possible");
    CHECK(original_source_classify(4095U, 0, true) == ORIGINAL_COMPRESSED,
          "upstream-near-page-compressed");
    CHECK(original_source_classify(PAGE_SIZE, 0, true) ==
          ORIGINAL_UNCOMPRESSED_4096, "upstream-exact-page-original-raw");
    CHECK(original_source_classify(PAGE_SIZE, 0, false) == ORIGINAL_INVALID,
          "upstream-incompressible-writeback-disabled");
    CHECK(original_source_classify(0U, 0, true) ==
          ORIGINAL_UNCOMPRESSED_4096, "upstream-zero-result-original-fallback");
    CHECK(original_source_classify(UINT_MAX, 0, true) ==
          ORIGINAL_UNCOMPRESSED_4096, "upstream-invalid-large-output-fallback");
    CHECK(!original_source_read_is_uncompressed(4095U),
          "upstream-compressed-read-must-decode");
    CHECK(original_source_read_is_uncompressed(PAGE_SIZE),
          "upstream-4096-read-must-copy-raw");
    CHECK(!original_source_read_is_uncompressed(4097U),
          "upstream-4097-not-a-stored-full-page");

    for (size_t index = 0U; index < sizeof(permitted_lengths) /
                                        sizeof(permitted_lengths[0]); ++index) {
        const unsigned int length = permitted_lengths[index];
        make_record(&record, original, compressed, length);
        CHECK(mock_stage(&record, mapping, compressed, length, &transaction) == 0,
              "current-import-length-in-range-admission-only");
        CHECK(transaction.phase == SWAPZ_ZSWAP_ADMISSION_PREPARED &&
              transaction.record.compressed_length == length &&
              transaction.upper_write_ack_count == 0U,
              "length-only-admission-has-no-durable-ack");
        swapz_zswap_admission_invalidate(&transaction);
    }
    for (size_t index = 0U; index < sizeof(forbidden_lengths) /
                                        sizeof(forbidden_lengths[0]); ++index) {
        const unsigned int length = forbidden_lengths[index];
        make_record(&record, original, compressed, length);
        CHECK(mock_stage(&record, mapping, compressed, length <= PAGE_SIZE + 1U ?
              length : (unsigned int)sizeof(compressed), &transaction) ==
              -EMSGSIZE, "dormant-import-reject-unrepresentable-compressed");
        CHECK(transaction.phase == SWAPZ_ZSWAP_ADMISSION_EMPTY &&
              transaction.upper_write_ack_count == 0U,
              "unrepresentable-must-not-stage-or-ack");
    }

    /* A short advertised source buffer must be rejected before CRC, even
     * when backing storage happens to have more bytes. */
    make_record(&record, original, compressed, 3568U);
    CHECK(mock_stage(&record, mapping, compressed, 3567U, &transaction) ==
          -EMSGSIZE, "short-claimed-import-source-capacity");
    CHECK(transaction.phase == SWAPZ_ZSWAP_ADMISSION_EMPTY,
          "short-source-never-staged");

    /* An opaque future 4095-byte stream fits physically even in a 4KiB
     * payload-only extent, but NO CURRENT DORMANT TYPED ORIGINAL IMPORT
     * may publish it. The first physical SWAPSPACE2 4096 and UUID do not
     * become a swapz metadata slot.
     */
    memset(physical, 0xa5, sizeof(physical));
    memcpy(original_header, physical, sizeof(original_header));
    for (unsigned int blocks = 1U; blocks <= 4U; blocks *= 2U) {
        const unsigned int extent_bytes = blocks * PAGE_SIZE;
        CHECK(extent_bytes == PAGE_SIZE || extent_bytes == 8192U ||
              extent_bytes == 16384U, "data-only-extent-4-8-16");
        CHECK(4095U <= extent_bytes, "future-opaque-physical-room-not-authorization");
        /* RAM ONLY: stage exact payload after the physically protected page
         * and deterministically pad ONLY the selected data-only extent. */
        memset(physical + SWAPZ_SUPERBLOCK_BYTES, 0, extent_bytes);
        memcpy(physical + SWAPZ_SUPERBLOCK_BYTES, compressed, 4095U);
        CHECK(memcmp(physical + SWAPZ_SUPERBLOCK_BYTES, compressed, 4095U) == 0,
              "payload-starts-after-protected-4096");
        for (unsigned int offset = 4095U; offset < extent_bytes; ++offset)
            CHECK(physical[SWAPZ_SUPERBLOCK_BYTES + offset] == 0U,
                  "zero-padded-data-only-extent");
        CHECK(memcmp(physical, original_header, PAGE_SIZE) == 0,
              "protected-first4096-unmodified");
    }

    /* Original PAGE_SIZE entry is the original UNCOMPRESSED folio, not
     * a compressed LZO1X/LZ4 blob nor a truncated compressed byte stream.
     */
    memset(output, 0x5a, PAGE_SIZE);
    CHECK(modeled_full_uncompressed_fallback(original, PAGE_SIZE, true,
                                            expected_sha256, output) == 0 &&
          memcmp(original, output, PAGE_SIZE) == 0,
          "full-original-uncompressed-raw4096");
    memset(output, 0x5a, PAGE_SIZE);
    CHECK(modeled_full_uncompressed_fallback(original, PAGE_SIZE - 1U, true,
                                            expected_sha256, output) == -ESTALE &&
          output[PAGE_SIZE - 1U] == 0x5aU,
          "short-4096-folio-must-not-masquerade-as-raw");
    CHECK(modeled_full_uncompressed_fallback(original, PAGE_SIZE, false,
                                            expected_sha256, output) == -ESTALE,
          "stale-source-must-not-authorize-raw");
    memcpy(corrupted_sha256, expected_sha256, sizeof(corrupted_sha256));
    corrupted_sha256[2] ^= 0x10U;
    CHECK(modeled_full_uncompressed_fallback(original, PAGE_SIZE, true,
                                            corrupted_sha256, output) == -EBADMSG,
          "wrong-original-digest-must-not-authorize-raw");

    make_record(&record, original, compressed, (unsigned int)compressed_length);
    read_authority = make_read_authority(&record);
    memset(scratch, 0x7f, PAGE_SIZE);
    memset(output, 0x5a, PAGE_SIZE);
    CHECK(swapz_zswap_import_decode(&record, &read_authority, compressed,
           (unsigned int)compressed_length, scratch, PAGE_SIZE,
           output, PAGE_SIZE, original) == 0,
          "valid-genuine-raw-block-lz4-original-decoding");
    CHECK(memcmp(original, output, PAGE_SIZE) == 0,
          "verified-full-original-page-output-including-last-byte");

    altered_record = record;
    altered_record.original_sha256[0] ^= 0x40U;
    memset(output, 0x5a, PAGE_SIZE);
    CHECK(swapz_zswap_import_decode(&altered_record, &read_authority,
           compressed, (unsigned int)compressed_length, scratch, PAGE_SIZE,
           output, PAGE_SIZE, original) == -EBADMSG &&
          output[PAGE_SIZE - 1U] == 0x5aU, "wrong-original-sha-no-partial-ack");

    altered_record = record;
    altered_record.codec = 0xffU;
    CHECK(swapz_zswap_import_decode(&altered_record, &read_authority,
           compressed, (unsigned int)compressed_length, scratch, PAGE_SIZE,
           output, PAGE_SIZE, original) == -EOPNOTSUPP,
          "wrong-original-codec-namespace");
    altered_record.codec = SWAPZ_ZSWAP_IMPORT_LZO1X_CODEC;
    CHECK(swapz_zswap_import_decode(&altered_record, &read_authority,
           compressed, (unsigned int)compressed_length, scratch, PAGE_SIZE,
           output, PAGE_SIZE, original) == -EOPNOTSUPP,
          "lzo1x-host-decoder-not-linked-not-fake-lz4");

    altered_record = record;
    altered_record.immutable_owned_copy = 0U;
    CHECK(swapz_zswap_import_decode(&altered_record, &read_authority,
           compressed, (unsigned int)compressed_length, scratch, PAGE_SIZE,
           output, PAGE_SIZE, original) == -EOPNOTSUPP,
          "borrowed-original-compressed-buffer-rejected");

    altered_read = read_authority;
    altered_read.current_owned_ram_session = 0U;
    CHECK(swapz_zswap_import_decode(&record, &altered_read, compressed,
           (unsigned int)compressed_length, scratch, PAGE_SIZE,
           output, PAGE_SIZE, original) == -ESTALE,
          "original-source-lifetime-revoked");
    altered_read = read_authority;
    altered_read.upper_write_ack_count = 0U;
    CHECK(swapz_zswap_import_decode(&record, &altered_read, compressed,
           (unsigned int)compressed_length, scratch, PAGE_SIZE,
           output, PAGE_SIZE, original) == -ESTALE, "no-false-upper-ack");
    altered_read = read_authority;
    altered_read.actual_lower_read_bytes = (unsigned int)compressed_length - 1U;
    CHECK(swapz_zswap_import_decode(&record, &altered_read, compressed,
           (unsigned int)compressed_length, scratch, PAGE_SIZE,
           output, PAGE_SIZE, original) == -EIO, "short-lower-read-detected");
    CHECK(swapz_zswap_import_decode(&record, &read_authority, compressed,
           (unsigned int)compressed_length - 1U, scratch, PAGE_SIZE,
           output, PAGE_SIZE, original) == -EMSGSIZE,
          "short-claimed-source-buffer-capacity");
    CHECK(swapz_zswap_import_decode(&record, &read_authority, compressed,
           (unsigned int)compressed_length, scratch, PAGE_SIZE,
           output, PAGE_SIZE - 1U, original) == -EMSGSIZE,
          "short-original-output-buffer-rejected");

    /* Decoder must reject >3568 BEFORE it can attempt to read/decode
     * arbitrary test bytes, even when capacity, CRC and authority match.
     */
    make_record(&altered_record, original, compressed, 3569U);
    altered_read = make_read_authority(&altered_record);
    CHECK(swapz_zswap_import_decode(&altered_record, &altered_read,
           compressed, 3569U, scratch, PAGE_SIZE, output, PAGE_SIZE,
           original) == -EMSGSIZE, "actual-decoder-reject-3569-before-decode");

    CHECK(swapz_zswap_admission_try_live(&transaction) == -EOPNOTSUPP,
          "no-real-original-source-carrier-active");
    make_record(&record, original, compressed, (unsigned int)compressed_length);
    mapping.post_header_extent_authorized = 0U;
    CHECK(mock_stage(&record, mapping, compressed,
                     (unsigned int)compressed_length, &transaction) ==
          -ESTALE, "first-4096-header-not-authorized-as-payload");
    mapping.post_header_extent_authorized = 1U;
    CHECK(mock_stage(&record, mapping, compressed,
                     (unsigned int)compressed_length, &transaction) == 0,
          "mock-stage-valid-real-lz4-stream");
    CHECK(swapz_zswap_admission_upper_write_ack(&transaction) == -ESTALE,
          "no-ack-before-lower-completion");
    CHECK(swapz_zswap_admission_lower_write_done(&transaction, 0,
                                                 PAGE_SIZE - 1U) == -EIO,
          "short-lower-write-must-not-publish");
    CHECK(swapz_zswap_admission_upper_write_ack(&transaction) == -ESTALE,
          "no-ack-after-partial-lower-write");
    CHECK(swapz_zswap_admission_lower_write_done(&transaction, 0,
                                                 PAGE_SIZE) == 0,
          "full-mocked-lower-write");
    CHECK(swapz_zswap_admission_publish_ram_mapping(&transaction,
           record.logical_page, record.generation, record.gc_epoch) == 0,
          "mock-ram-mapping-after-lower");
    CHECK(swapz_zswap_admission_upper_write_ack(&transaction) == 0,
          "exactly-one-mock-write-ack");
    CHECK(swapz_zswap_admission_upper_write_ack(&transaction) == -ESTALE,
          "duplicate-mock-write-ack-rejected");
    memset(output, 0x5a, PAGE_SIZE);
    CHECK(swapz_zswap_admission_read_4096(&transaction, record.logical_page,
          record.generation, record.gc_epoch, compressed, PAGE_SIZE, 0,
          scratch, output, original) == 0 &&
          memcmp(output, original, PAGE_SIZE) == 0,
          "genuine-lz4-read-only-after-mock-durable-publish");
    swapz_zswap_admission_invalidate(&transaction);
    CHECK(swapz_zswap_admission_upper_write_ack(&transaction) == -ESTALE,
          "teardown-must-not-reack");

    puts("ROUND078_LENGTH_SOURCE_C_PASS upstream=PINNED_BRANCHES "
         "product_limit=3568 upstream_compressed_possible=1..4095 "
         "raw4096=FULL_ORIGINAL_UNCOMPRESSED lz4=GENUINE_RAW_BLOCK "
         "lzo1x_decode=NOT_COVERED source_auth=0 physical_io=0 "
         "original_native=NOT_RUN");
    return 0;
}
