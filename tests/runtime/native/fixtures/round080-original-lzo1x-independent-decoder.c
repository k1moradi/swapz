/* SPDX-License-Identifier: GPL-2.0-only */
/*
 * Round080 Agent7: original pinned Linux LZO1X bytes decoded by the real
 * dormant product original-import decoder under its own retained reader lease.
 * Authority is ONLY a synthetic test record; no live STORED/DM, disk or BIO.
 */
#define _POSIX_C_SOURCE 200809L
#include <errno.h>
#include <pthread.h>
#include <sched.h>
#include <stdatomic.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <openssl/sha.h>
#include "zswap-import-decoder-owner.h"
#include "zswap-direct-handoff.h"
#include "authority.h"

#define SOURCE_MAPPED_AUTHENTICATED 0
#define PHASE_A_BLOCKED 1
#define FORCED_RAW_BYPASS 0
#define DIRECT_COMPRESSED_HANDOFF 0

_Static_assert(SWAPZ_BLOCK_BYTES == 4096U, "uncompressed RAW 4096");
_Static_assert(SWAPZ_MAX_COMPRESSED == 3568U, "fail closed at 3569");
_Static_assert(SWAPZ_ZSWAP_IMPORT_LZO1X_CODEC == 2U, "original LZO tag2");
_Static_assert(SWAPZ_ZSWAP_IMPORT_LZ4_CODEC == 1U, "original LZ4 tag1");
_Static_assert(SWAPZ_DIRECT_ZSWAP_ZSTD == 2, "legacy direct tag2 ZSTD");
_Static_assert(SWAPZ_ZSWAP_IMPORT_ACTIVE == 0U, "import disabled");
_Static_assert(SWAPZ_DIRECT_HANDOFF_PRODUCTION_ENABLED == 0U, "direct disabled");
_Static_assert(SWAPZ_CODEC_METADATA_ON_MEDIA == 0U, "volatile descriptors");
_Static_assert(SWAPZ_LINUX_SWAP_HEADER_BLOCKS == 1U, "protected first 4096");
_Static_assert(sizeof(struct swapz_map) == 20U, "RAM map exactly 20 bytes");

static unsigned int directed_checks;
static unsigned char original_page[SWAPZ_BLOCK_BYTES];
static unsigned char original_lzo[SWAPZ_BLOCK_BYTES + 512U];
static unsigned char decode_scratch[SWAPZ_BLOCK_BYTES];
static unsigned char decoded_page[SWAPZ_BLOCK_BYTES];
static unsigned char compressor_workspace[LZO1X_1_MEM_COMPRESS]
    __attribute__((aligned(16)));
static size_t original_lzo_length;
static struct swapz_zswap_import_record record;
static struct swapz_zswap_import_read_authority authority;
static struct swapz_zswap_import_decoder_owner decoder_owner;
static struct swapz_zswap_import_decoder_lease reader_lease;

static void require_case(const char *name, bool holds, int observed)
{
    ++directed_checks;
    if (!holds) {
        fprintf(stderr, "FIRST_ERROR check=%s line=%d observed=%d\n",
                name, __LINE__, observed);
        exit(1);
    }
}

static void expect_rejected(const char *name,
        struct swapz_zswap_import_record candidate,
        struct swapz_zswap_import_read_authority witnessed,
        const unsigned char *bytes, swapz_u32 capacity,
        unsigned char *scratch, swapz_u32 scratch_bytes,
        unsigned char *output, swapz_u32 output_bytes, int expected)
{
    int result;
    memset(output, 0xa5, SWAPZ_BLOCK_BYTES);
    result = swapz_zswap_import_decoder_owner_decode(
        &reader_lease, &candidate, &witnessed, bytes, capacity,
        scratch, scratch_bytes, output, output_bytes, original_page);
    require_case(name, result == expected, result);
    for (size_t index = 0; index < SWAPZ_BLOCK_BYTES; ++index) {
        if (output[index] != 0xa5) {
            require_case(name, false, (int)index);
        }
    }
}

static void expected_failure(const char *name,
        struct swapz_zswap_import_record candidate,
        struct swapz_zswap_import_read_authority witnessed,
        int expected)
{
    expect_rejected(name, candidate, witnessed, original_lzo,
                    (swapz_u32)original_lzo_length,
                    decode_scratch, SWAPZ_BLOCK_BYTES,
                    decoded_page, SWAPZ_BLOCK_BYTES, expected);
}

static void *close_decoder(void *argument)
{
    struct swapz_zswap_import_decoder_owner *owner = argument;
    int result = swapz_zswap_import_decoder_owner_close_and_drain(owner);
    return (void *)(intptr_t)result;
}

int main(void)
{
    size_t direct_output_length;
    unsigned char direct_output[SWAPZ_BLOCK_BYTES];
    size_t shortened_length = sizeof(original_lzo);
    unsigned char corrupted[sizeof(original_lzo)];
    struct swapz_zswap_import_record candidate;
    struct swapz_zswap_import_read_authority witnessed;
    pthread_t closing_thread;
    void *closing_result = NULL;
    struct swapz_zswap_import_decoder_lease second_lease = { 0 };
    int result;

    for (size_t index = 0; index < SWAPZ_BLOCK_BYTES; ++index) {
        /* Compressible, non-constant full original page (not an LZ4 stream). */
        original_page[index] = (unsigned char)((index / 37U + index % 13U) & 0x7fU);
    }
    original_lzo_length = sizeof(original_lzo);
    result = lzo1x_1_compress_safe(original_page, SWAPZ_BLOCK_BYTES,
                                  original_lzo, &original_lzo_length,
                                  compressor_workspace);
    require_case("pinned_original_lzo_compress", result == LZO_E_OK, result);
    require_case("real_lzo_bounded_nonraw", original_lzo_length > 0U &&
                 original_lzo_length < SWAPZ_MAX_COMPRESSED &&
                 original_lzo_length != SWAPZ_BLOCK_BYTES, (int)original_lzo_length);
    direct_output_length = sizeof(direct_output);
    result = lzo1x_decompress_safe(original_lzo, original_lzo_length,
                                   direct_output, &direct_output_length);
    require_case("original_compressor_decoder_interoperable",
                 result == LZO_E_OK && direct_output_length == SWAPZ_BLOCK_BYTES &&
                 memcmp(original_page, direct_output, SWAPZ_BLOCK_BYTES) == 0, result);

    record.logical_page = 123U;
    record.generation = 456U;
    record.stored_entry_identity = 789U;
    record.store_generation = 22U;
    record.gc_epoch = 33U;
    record.compressed_length = (swapz_u32)original_lzo_length;
    record.decoded_length = SWAPZ_BLOCK_BYTES;
    record.compressed_crc32c = swapz_crc32c_bytes(original_lzo, record.compressed_length);
    require_case("original_sha256", SHA256(original_page, SWAPZ_BLOCK_BYTES,
                 record.original_sha256) != NULL, 0);
    record.representation = SWAPZ_ZSWAP_IMPORT_REPRESENTATION;
    record.codec = SWAPZ_ZSWAP_IMPORT_LZO1X_CODEC;
    record.version = SWAPZ_ZSWAP_IMPORT_LZO1X_VERSION;
    record.dictionary_id = 0U;
    record.stored_eviction = 1U;
    record.immutable_owned_copy = 1U;
    authority.logical_page = record.logical_page;
    authority.generation = record.generation;
    authority.stored_entry_identity = record.stored_entry_identity;
    authority.store_generation = record.store_generation;
    authority.gc_epoch = record.gc_epoch;
    authority.actual_lower_read_bytes = record.compressed_length;
    authority.lower_read_error = 0;
    authority.mapping_published_after_durable_write = 1U; /* TEST-ONLY witness */
    authority.foreground_write_committed_once = 1U;        /* TEST-ONLY witness */
    authority.upper_write_ack_count = 1U;                   /* TEST-ONLY witness */
    authority.current_owned_ram_session = 1U;               /* TEST-ONLY witness */
    authority.teardown_started = 0U;
    authority.upper_read_ack_count = 0U;

    result = swapz_zswap_import_decoder_owner_init(&decoder_owner,
                    SWAPZ_ZSWAP_IMPORT_LZO1X_CODEC, SWAPZ_ZSWAP_IMPORT_LZO1X_VERSION);
    require_case("owner_initialized", result == 0, result);
    result = swapz_zswap_import_decoder_owner_get(&decoder_owner, &reader_lease);
    require_case("original_lease_acquired", result == 0, result);
    result = swapz_zswap_import_decoder_owner_get(&decoder_owner, &reader_lease);
    require_case("duplicate_get_refused", result == -EBUSY, result);
    memset(decoded_page, 0xa5, sizeof(decoded_page));
    result = swapz_zswap_import_decoder_owner_decode(
        &reader_lease, &record, &authority, original_lzo, record.compressed_length,
        decode_scratch, SWAPZ_BLOCK_BYTES, decoded_page, SWAPZ_BLOCK_BYTES,
        original_page);
    require_case("positive_dormant_product_lzo_decode", result == 0 &&
                 memcmp(decoded_page, original_page, SWAPZ_BLOCK_BYTES) == 0, result);
    require_case("typed_tag2_no_legacy_zstd",
                 SWAPZ_DIRECT_ZSWAP_ZSTD == (int)record.codec &&
                 record.codec == SWAPZ_ZSWAP_IMPORT_LZO1X_CODEC, 0);

    candidate = record; candidate.representation ^= 1U;
    expected_failure("representation", candidate, authority, -EOPNOTSUPP);
    candidate = record; candidate.codec = 3U;
    expected_failure("wrong_original_codec", candidate, authority, -EOPNOTSUPP);
    candidate = record; candidate.version = 2U;
    /* The retained lease rejects stale versions before the inner decoder.
     * Also exercise the independently defended dormant import version guard
     * directly, so a real guard mutant cannot hide behind its outer lease. */
    expected_failure("version_lease", candidate, authority, -EOPNOTSUPP);
    memset(decoded_page, 0xa5, sizeof(decoded_page));
    result = swapz_zswap_import_decode(&candidate, &authority, original_lzo,
                 record.compressed_length, decode_scratch, SWAPZ_BLOCK_BYTES,
                 decoded_page, SWAPZ_BLOCK_BYTES, original_page);
    require_case("version", result == -EOPNOTSUPP, result);
    require_case("version_direct_failure_unchanged",
                 decoded_page[0] == 0xa5 &&
                 decoded_page[SWAPZ_BLOCK_BYTES - 1U] == 0xa5, result);
    candidate = record; candidate.dictionary_id = 1U;
    expected_failure("dictionary", candidate, authority, -EOPNOTSUPP);
    candidate = record; candidate.stored_eviction = 0U;
    expected_failure("not_original_stored_eviction", candidate, authority, -EOPNOTSUPP);
    candidate = record; candidate.immutable_owned_copy = 0U;
    expected_failure("no_owned_copy", candidate, authority, -EOPNOTSUPP);
    candidate = record; candidate.decoded_length = 4095U;
    expected_failure("decoded_4095", candidate, authority, -EMSGSIZE);
    candidate = record; candidate.compressed_length = 3569U;
    witnessed = authority; witnessed.actual_lower_read_bytes = 3569U;
    expect_rejected("3569_rejected_not_truncated", candidate, witnessed,
                    original_lzo, 3569U, decode_scratch, SWAPZ_BLOCK_BYTES,
                    decoded_page, SWAPZ_BLOCK_BYTES, -EMSGSIZE);
    expect_rejected("capacity_short", record, authority, original_lzo,
                    (swapz_u32)original_lzo_length - 1U,
                    decode_scratch, SWAPZ_BLOCK_BYTES, decoded_page,
                    SWAPZ_BLOCK_BYTES, -EMSGSIZE);
    witnessed = authority; witnessed.generation += 1U;
    expected_failure("stale_generation", record, witnessed, -ESTALE);
    witnessed = authority; witnessed.upper_write_ack_count = 0U;
    expected_failure("not_exactly_once_upper_write_ack", record, witnessed, -ESTALE);
    witnessed = authority; witnessed.actual_lower_read_bytes -= 1U;
    expected_failure("partial_lower_read", record, witnessed, -EIO);
    witnessed = authority; witnessed.lower_read_error = -EIO;
    expected_failure("lower_io_error", record, witnessed, -EIO);
    candidate = record; candidate.compressed_crc32c ^= 1U;
    expected_failure("corrupt_compressed_crc", candidate, authority, -EBADMSG);
    candidate = record; candidate.original_sha256[0] ^= 1U;
    expected_failure("corrupt_original_sha", candidate, authority, -EBADMSG);
    expect_rejected("overlap_scratch_output", record, authority, original_lzo,
                    (swapz_u32)original_lzo_length, decoded_page,
                    SWAPZ_BLOCK_BYTES, decoded_page, SWAPZ_BLOCK_BYTES, -EINVAL);
    candidate = record; candidate.compressed_length = SWAPZ_BLOCK_BYTES;
    expected_failure("full_4096_is_uncompressed_raw", candidate, authority, -EMSGSIZE);
    candidate = record; candidate.codec = SWAPZ_ZSWAP_IMPORT_LZ4_CODEC;
    expected_failure("lzo_stream_not_raw_lz4", candidate, authority, -EOPNOTSUPP);
    corrupted[0] = 0U;
    memcpy(corrupted, original_lzo, original_lzo_length);
    corrupted[original_lzo_length / 2U] ^= 0x80U;
    candidate = record;
    candidate.compressed_crc32c = swapz_crc32c_bytes(corrupted, record.compressed_length);
    expect_rejected("mutated_lzo_bytes", candidate, authority, corrupted,
                    record.compressed_length, decode_scratch, SWAPZ_BLOCK_BYTES,
                    decoded_page, SWAPZ_BLOCK_BYTES, -EBADMSG);
    memcpy(corrupted, original_lzo, original_lzo_length);
    corrupted[original_lzo_length] = 0x7eU;
    candidate = record; candidate.compressed_length += 1U;
    candidate.compressed_crc32c = swapz_crc32c_bytes(corrupted, candidate.compressed_length);
    witnessed = authority; witnessed.actual_lower_read_bytes = candidate.compressed_length;
    direct_output_length = SWAPZ_BLOCK_BYTES;
    result = lzo1x_decompress_safe(corrupted, candidate.compressed_length,
                                   direct_output, &direct_output_length);
    require_case("original_lzo_input_not_consumed", result == LZO_E_INPUT_NOT_CONSUMED, result);
    expect_rejected("trailing_lzo_input", candidate, witnessed, corrupted,
                    candidate.compressed_length, decode_scratch, SWAPZ_BLOCK_BYTES,
                    decoded_page, SWAPZ_BLOCK_BYTES, -EBADMSG);
    result = lzo1x_1_compress_safe(original_page, SWAPZ_BLOCK_BYTES - 1U,
                    corrupted, &shortened_length, compressor_workspace);
    require_case("short_lzo_compress", result == LZO_E_OK, result);
    candidate = record; candidate.compressed_length = (swapz_u32)shortened_length;
    candidate.compressed_crc32c = swapz_crc32c_bytes(corrupted, candidate.compressed_length);
    witnessed = authority; witnessed.actual_lower_read_bytes = candidate.compressed_length;
    expect_rejected("lzo_decodes_only_4095", candidate, witnessed, corrupted,
                    candidate.compressed_length, decode_scratch, SWAPZ_BLOCK_BYTES,
                    decoded_page, SWAPZ_BLOCK_BYTES, -EBADMSG);

    /* Owner.close cannot return until the old reader drops the retained lease. */
    result = pthread_create(&closing_thread, NULL, close_decoder, &decoder_owner);
    require_case("close_thread_created", result == 0, result);
    bool closing_started = false;
    for (unsigned int attempt = 0U; attempt < 1000000U; ++attempt) {
        result = pthread_mutex_lock(&decoder_owner.lock);
        require_case("owner_lock", result == 0, result);
        closing_started = decoder_owner.closing != 0U;
        result = pthread_mutex_unlock(&decoder_owner.lock);
        require_case("owner_unlock", result == 0, result);
        if (closing_started) break;
        sched_yield();
    }
    require_case("close_started_bounded", closing_started, 0);
    result = swapz_zswap_import_decoder_owner_get(&decoder_owner, &second_lease);
    require_case("retired_decoder_refuses_new_reader", result == -ESHUTDOWN, result);
    memset(decoded_page, 0xa5, sizeof(decoded_page));
    result = swapz_zswap_import_decoder_owner_decode(
        &reader_lease, &record, &authority, original_lzo, record.compressed_length,
        decode_scratch, SWAPZ_BLOCK_BYTES, decoded_page, SWAPZ_BLOCK_BYTES,
        original_page);
    require_case("old_reader_retains_original_decoder", result == 0 &&
                 memcmp(decoded_page, original_page, SWAPZ_BLOCK_BYTES) == 0, result);
    require_case("close_still_has_old_reader",
                 decoder_owner.active_readers == 1U, (int)decoder_owner.active_readers);
    result = swapz_zswap_import_decoder_owner_put(&reader_lease);
    require_case("lease_put_once", result == 0, result);
    result = swapz_zswap_import_decoder_owner_put(&reader_lease);
    require_case("duplicate_put", result == -EALREADY, result);
    result = pthread_join(closing_thread, &closing_result);
    require_case("drain_join", result == 0 && (intptr_t)closing_result == 0, result);
    result = swapz_zswap_import_decoder_owner_get(&decoder_owner, &second_lease);
    require_case("retired_owner_remains_closed", result == -ESHUTDOWN, result);
    require_case("no_reader_leak", decoder_owner.active_readers == 0U, 0);
    result = pthread_cond_destroy(&decoder_owner.drained);
    require_case("destroy_drained_cond", result == 0, result);
    result = pthread_mutex_destroy(&decoder_owner.lock);
    require_case("destroy_drained_lock", result == 0, result);
    printf("PASS round080-agent7 source_original_lzo1x_to_product_decode=1 "
           "retained_lease=1 original_4096=1 AUTH=0 PHASE_A=BLOCKED checks=%u\n",
           directed_checks);
    return 0;
}
