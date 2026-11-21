/* SPDX-License-Identifier: GPL-2.0-only */
/* Synthetic imported-only volatile descriptor lifecycle. NO production authority. */
#include <errno.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <lz4.h>
#include <openssl/sha.h>
#include "../../../../src/kernel/codec.h"

#define SOURCE_MAPPED_AUTHENTICATED 0
#define DIRECT_COMPRESSED_HANDOFF 0
#define FORCED_RAW_BYPASS 0

enum { LOGICAL_PAGES = 4, DESCRIPTORS = 8, DISK_BLOCKS = 16,
       CODEC_RAW_LZ4_V1 = 1, IMPORT_REPRESENTATION = 0x5a,
       MAX_STAGING = 2, HEADER_BYTES = 4096 };

typedef struct {
    uint64_t session;
    uint64_t generation;
    uint64_t source_identity;
    uint32_t gc_epoch;
    uint32_t disk_block;
    uint32_t length;
    uint32_t compressed_crc;
    uint8_t original_sha[SHA256_DIGEST_LENGTH];
    uint16_t reader_pins;
    uint8_t decoder_id;
    uint8_t representation;
    uint8_t codec_version;
    bool reserved;
    bool published;
    bool retired;
    bool lower_completed;
    bool durable;
    bool flushed;
} descriptor;

typedef struct {
    uint64_t session;
    uint64_t generation;
    uint8_t descriptor_index;
    bool imported;
    bool valid;
} mapping;

typedef struct {
    descriptor entries[DESCRIPTORS];
    mapping maps[LOGICAL_PAGES];
    uint8_t disk[DISK_BLOCKS][SWAPZ_BLOCK_BYTES];
    uint8_t header_shadow[HEADER_BYTES];
    uint8_t partition_table[64];
    uint16_t decoder_refs;
    uint8_t staging_count;
    uint8_t ack_counts[LOGICAL_PAGES];
    uint32_t gc_epoch;
    uint64_t active_session;
    bool closing;
} model;

static model state;
static unsigned int cases;
static unsigned int rejects;
#define CHECK(guard, name) do { if (!(guard)) { \
    fprintf(stderr, "FIRST_ERROR %s\n", name); return 1; } } while (0)

static uint32_t crc32c(const uint8_t *bytes, size_t length)
{
    uint32_t crc = UINT32_MAX;
    for (size_t index = 0; index < length; ++index) {
        crc ^= bytes[index];
        for (unsigned int bit = 0; bit < 8U; ++bit)
            crc = (crc >> 1) ^ ((crc & 1U) ? UINT32_C(0x82f63b78) : 0U);
    }
    return ~crc;
}

static void initialize(void)
{
    memset(&state, 0, sizeof(state));
    state.active_session = 11U;
    state.gc_epoch = 1U;
    for (size_t index = 0; index < HEADER_BYTES; ++index)
        state.disk[0][index] = (uint8_t)(index * 17U + 3U);
    memcpy(state.header_shadow, state.disk[0], HEADER_BYTES);
    for (size_t index = 0; index < sizeof(state.partition_table); ++index)
        state.partition_table[index] = (uint8_t)(index + 67U);
}

static bool header_unchanged(void)
{
    if (memcmp(state.disk[0], state.header_shadow, HEADER_BYTES))
        return false;
    for (size_t index = 0; index < sizeof(state.partition_table); ++index)
        if (state.partition_table[index] != (uint8_t)(index + 67U))
            return false;
    return true;
}

static void fill_original(uint8_t *page, unsigned int seed)
{
    memset(page, (int)(seed & 255U), SWAPZ_BLOCK_BYTES);
    page[0] ^= (uint8_t)seed;
    page[SWAPZ_BLOCK_BYTES - 1U] ^= (uint8_t)(seed + 13U);
}

static int encode(const uint8_t *page, uint8_t *compressed)
{
    return LZ4_compress_default((const char *)page, (char *)compressed,
                                (int)SWAPZ_BLOCK_BYTES, (int)SWAPZ_MAX_COMPRESSED);
}

static unsigned int free_block(void)
{
    for (unsigned int block = 1U; block < DISK_BLOCKS; ++block) {
        bool used = false;
        for (unsigned int index = 0; index < DESCRIPTORS; ++index)
            if (state.entries[index].reserved &&
                state.entries[index].disk_block == block)
                used = true;
        if (!used)
            return block;
    }
    return 0U;
}

static int reserve_import(unsigned int logical, uint64_t generation,
                          uint64_t source_identity, const uint8_t *original,
                          const uint8_t *compressed, unsigned int length)
{
    if (logical >= LOGICAL_PAGES || !source_identity || !generation ||
        !compressed || !original || !length || length > SWAPZ_MAX_COMPRESSED ||
        state.closing || state.staging_count >= MAX_STAGING)
        return -EINVAL;
    unsigned int block = free_block();
    if (!block)
        return -ENOSPC;
    for (unsigned int index = 0; index < DESCRIPTORS; ++index) {
        descriptor *record = &state.entries[index];
        if (record->reserved)
            continue;
        memset(record, 0, sizeof(*record));
        record->reserved = true;
        record->session = state.active_session;
        record->generation = generation;
        record->source_identity = source_identity;
        record->gc_epoch = state.gc_epoch;
        record->disk_block = block;
        record->length = length;
        record->compressed_crc = crc32c(compressed, length);
        record->decoder_id = CODEC_RAW_LZ4_V1;
        record->representation = IMPORT_REPRESENTATION;
        record->codec_version = 1U;
        (void)SHA256(original, SWAPZ_BLOCK_BYTES, record->original_sha);
        memcpy(state.disk[block], compressed, length);
        memset(state.disk[block] + length, 0, SWAPZ_BLOCK_BYTES - length);
        ++state.staging_count;
        ++state.decoder_refs;
        return (int)index;
    }
    return -ENOSPC;
}

static void discard_staging(unsigned int index)
{
    descriptor *record = &state.entries[index];
    if (!record->reserved || record->published)
        return;
    --state.staging_count;
    --state.decoder_refs;
    memset(record, 0, sizeof(*record));
}

static int complete_write(unsigned int logical, unsigned int index,
                          uint64_t expected_generation, bool lower_ok,
                          bool fua_completed, bool explicit_flush_completed)
{
    if (logical >= LOGICAL_PAGES || index >= DESCRIPTORS)
        return -EINVAL;
    descriptor *record = &state.entries[index];
    if (!record->reserved || record->published || state.closing ||
        record->session != state.active_session ||
        record->generation != expected_generation ||
        record->gc_epoch != state.gc_epoch)
        return -ESTALE;
    if (!lower_ok)
        return -EIO;
    record->lower_completed = true;
    record->flushed = explicit_flush_completed;
    record->durable = fua_completed || explicit_flush_completed;
    if (!record->durable)
        return -EAGAIN;
    mapping *current = &state.maps[logical];
    if (current->valid && expected_generation <= current->generation)
        return -ESTALE;
    /* One serialized transaction: new descriptor and authoritative map agree. */
    record->published = true;
    *current = (mapping){ .session = state.active_session,
                          .generation = expected_generation,
                          .descriptor_index = (uint8_t)index,
                          .imported = true, .valid = true };
    ++state.ack_counts[logical];
    --state.staging_count;
    return 0;
}

static int retire(unsigned int index)
{
    descriptor *record = &state.entries[index];
    if (!record->reserved || !record->published)
        return -EINVAL;
    if (record->reader_pins)
        return -EBUSY;
    for (unsigned int logical = 0; logical < LOGICAL_PAGES; ++logical)
        if (state.maps[logical].valid &&
            state.maps[logical].descriptor_index == index)
            return -EBUSY;
    --state.decoder_refs;
    memset(record, 0, sizeof(*record));
    return 0;
}

static int pin_read(unsigned int logical, unsigned int *index)
{
    if (logical >= LOGICAL_PAGES || !index || state.closing)
        return -EINVAL;
    const mapping *map = &state.maps[logical];
    if (!map->valid || !map->imported || map->session != state.active_session ||
        map->descriptor_index >= DESCRIPTORS)
        return -ENOENT;
    descriptor *record = &state.entries[map->descriptor_index];
    if (!record->published || !record->reserved || record->retired ||
        record->representation != IMPORT_REPRESENTATION ||
        record->decoder_id != CODEC_RAW_LZ4_V1 || record->codec_version != 1U ||
        record->session != map->session || record->generation != map->generation)
        return -ESTALE;
    ++record->reader_pins;
    ++state.decoder_refs;
    *index = map->descriptor_index;
    return 0;
}

static void unpin_read(unsigned int index)
{
    --state.entries[index].reader_pins;
    --state.decoder_refs;
}

static int decode_pinned(unsigned int index, uint8_t *output)
{
    const descriptor *record = &state.entries[index];
    uint8_t scratch[SWAPZ_BLOCK_BYTES], original_digest[SHA256_DIGEST_LENGTH];
    if (!record->reader_pins || !record->reserved || !record->published ||
        record->length > SWAPZ_MAX_COMPRESSED || record->disk_block == 0U ||
        record->disk_block >= DISK_BLOCKS)
        return -ESTALE;
    const uint8_t *compressed = state.disk[record->disk_block];
    if (crc32c(compressed, record->length) != record->compressed_crc)
        return -EBADMSG;
    if (LZ4_decompress_safe((const char *)compressed, (char *)scratch,
                            (int)record->length, (int)SWAPZ_BLOCK_BYTES) !=
        (int)SWAPZ_BLOCK_BYTES)
        return -EBADMSG;
    (void)SHA256(scratch, SWAPZ_BLOCK_BYTES, original_digest);
    if (memcmp(original_digest, record->original_sha, SHA256_DIGEST_LENGTH))
        return -EBADMSG;
    memcpy(output, scratch, SWAPZ_BLOCK_BYTES);
    return 0;
}

static int relocate_gc(unsigned int logical, unsigned int new_block, bool lower_ok,
                       bool durable, bool commit_current)
{
    if (logical >= LOGICAL_PAGES || new_block == 0U || new_block >= DISK_BLOCKS)
        return -EINVAL;
    const mapping *map = &state.maps[logical];
    if (!map->valid || !map->imported)
        return -ENOENT;
    descriptor *record = &state.entries[map->descriptor_index];
    if (!record->published || record->reader_pins || !record->reserved ||
        record->session != state.active_session ||
        record->generation != map->generation)
        return -EBUSY;
    for (unsigned int index = 0; index < DESCRIPTORS; ++index)
        if (state.entries[index].reserved && state.entries[index].disk_block == new_block)
            return -ENOSPC;
    uint8_t scratch[SWAPZ_BLOCK_BYTES];
    memcpy(scratch, state.disk[record->disk_block], SWAPZ_BLOCK_BYTES);
    if (!lower_ok)
        return -EIO;
    if (!durable || !commit_current || state.closing)
        return -EAGAIN;
    /* GC moves opaque payload and immutable decoding identity together. */
    memcpy(state.disk[new_block], scratch, SWAPZ_BLOCK_BYTES);
    record->disk_block = new_block;
    ++record->gc_epoch;
    return 0;
}

static int test_lifecycle(void)
{
    uint8_t original[SWAPZ_BLOCK_BYTES], second[SWAPZ_BLOCK_BYTES];
    uint8_t compressed[SWAPZ_MAX_COMPRESSED], output[SWAPZ_BLOCK_BYTES];
    unsigned int pinned;
    initialize();
    fill_original(original, 71U);
    int length = encode(original, compressed);
    CHECK(length > 0 && length <= (int)SWAPZ_MAX_COMPRESSED, "codec_length");
    int first = reserve_import(0U, 1U, 101U, original, compressed, (unsigned int)length);
    CHECK(first >= 0 && state.staging_count == 1U, "reserve_before_write");
    CHECK(!state.maps[0].valid && !state.ack_counts[0], "no_early_map");
    CHECK(complete_write(0U, (unsigned int)first, 1U, true, false, false) == -EAGAIN &&
          !state.maps[0].valid, "durability_required");
    CHECK(complete_write(0U, (unsigned int)first, 1U, true, true, false) == 0 &&
          state.maps[0].valid && state.ack_counts[0] == 1U, "map_after_durable");
    CHECK(complete_write(0U, (unsigned int)first, 1U, true, true, false) == -ESTALE &&
          state.ack_counts[0] == 1U, "one_ack");
    CHECK(pin_read(0U, &pinned) == 0 && pinned == (unsigned int)first, "pin_reader");
    CHECK(decode_pinned(pinned, output) == 0 &&
          memcmp(output, original, SWAPZ_BLOCK_BYTES) == 0, "full_page_read");
    CHECK(relocate_gc(0U, 12U, true, true, true) == -EBUSY, "gc_reader_pin");
    CHECK(retire((unsigned int)first) == -EBUSY, "decoder_pinned");
    unpin_read(pinned);
    CHECK(relocate_gc(0U, 12U, false, true, true) == -EIO &&
          state.entries[first].disk_block != 12U, "gc_eio_rollback");
    CHECK(relocate_gc(0U, 12U, true, false, true) == -EAGAIN &&
          state.entries[first].disk_block != 12U, "gc_durable");
    CHECK(relocate_gc(0U, 12U, true, true, false) == -EAGAIN &&
          state.entries[first].disk_block != 12U, "gc_stale");
    CHECK(relocate_gc(0U, 12U, true, true, true) == 0 &&
          state.entries[first].disk_block == 12U, "gc_move");
    CHECK(pin_read(0U, &pinned) == 0 && decode_pinned(pinned, output) == 0 &&
          memcmp(output, original, SWAPZ_BLOCK_BYTES) == 0, "gc_full_page");
    unpin_read(pinned);
    fill_original(second, 139U);
    length = encode(second, compressed);
    CHECK(length > 0, "replacement_codec");
    int next = reserve_import(0U, 2U, 102U, second, compressed, (unsigned int)length);
    CHECK(next >= 0, "replacement_reserve");
    CHECK(complete_write(0U, (unsigned int)next, 2U, false, true, false) == -EIO &&
          state.maps[0].descriptor_index == (unsigned int)first, "replacement_eio_rollback");
    discard_staging((unsigned int)next);
    CHECK(state.decoder_refs == 1U, "rollback_decoder_release");
    next = reserve_import(0U, 2U, 102U, second, compressed, (unsigned int)length);
    CHECK(next >= 0, "retry_reserve");
    CHECK(complete_write(0U, (unsigned int)next, 1U, true, true, false) == -ESTALE &&
          state.maps[0].descriptor_index == (unsigned int)first, "late_reissue");
    CHECK(complete_write(0U, (unsigned int)next, 2U, true, true, false) == 0 &&
          state.ack_counts[0] == 2U, "retry_map");
    CHECK(retire((unsigned int)first) == 0, "old_map_retire");
    CHECK(pin_read(0U, &pinned) == 0 && decode_pinned(pinned, output) == 0 &&
          memcmp(output, second, SWAPZ_BLOCK_BYTES) == 0, "new_full_page");
    state.disk[state.entries[pinned].disk_block][0] ^= 1U;
    memset(output, 0x77, sizeof(output));
    CHECK(decode_pinned(pinned, output) == -EBADMSG && output[0] == 0x77U,
          "corruption_no_raw_fallback");
    unpin_read(pinned);
    state.closing = true;
    CHECK(pin_read(0U, &pinned) == -EINVAL, "teardown_no_reads");
    CHECK(state.decoder_refs == 1U, "decoder_survives_map");
    CHECK(header_unchanged(), "protected_header");
    ++cases;
    return 0;
}

static int test_resource_bounds(void)
{
    uint8_t page[SWAPZ_BLOCK_BYTES], compressed[SWAPZ_MAX_COMPRESSED];
    initialize();
    fill_original(page, 8U);
    int length = encode(page, compressed);
    CHECK(length > 0, "capacity_codec");
    int first = reserve_import(0U, 1U, 101U, page, compressed, (unsigned int)length);
    CHECK(first >= 0, "capacity_first");
    int second = reserve_import(1U, 1U, 102U, page, compressed, (unsigned int)length);
    CHECK(second >= 0 && state.staging_count == 2U, "staging_two");
    CHECK(reserve_import(2U, 1U, 103U, page, compressed, (unsigned int)length) == -EINVAL,
          "bounded_staging");
    discard_staging((unsigned int)first);
    discard_staging((unsigned int)second);
    CHECK(state.staging_count == 0U && state.decoder_refs == 0U, "staging_release");
    CHECK(!state.maps[0].valid && !state.maps[1].valid, "exhaustion_no_map");
    CHECK(header_unchanged(), "capacity_header");
    ++cases;
    return 0;
}

static int oracle(const char *name)
{
    if (!strcmp(name, "durability")) {
        uint8_t page[SWAPZ_BLOCK_BYTES], compressed[SWAPZ_MAX_COMPRESSED];
        initialize(); fill_original(page, 9U);
        int length = encode(page, compressed);
        int index = reserve_import(0U, 1U, 1U, page, compressed, (unsigned int)length);
        CHECK(index >= 0, "oracle_setup");
        CHECK(complete_write(0U, (unsigned int)index, 1U, true, false, false) == -EAGAIN,
              "durability_required");
    } else if (!strcmp(name, "replay")) {
        uint8_t page[SWAPZ_BLOCK_BYTES], compressed[SWAPZ_MAX_COMPRESSED];
        initialize(); fill_original(page, 9U);
        int length = encode(page, compressed);
        int index = reserve_import(0U, 1U, 1U, page, compressed, (unsigned int)length);
        CHECK(index >= 0, "oracle_setup");
        CHECK(complete_write(0U, (unsigned int)index, 1U, true, true, false) == 0, "oracle_first");
        CHECK(complete_write(1U, (unsigned int)index, 1U, true, true, false) == -ESTALE,
              "one_ack");
    } else if (!strcmp(name, "pin")) {
        uint8_t page[SWAPZ_BLOCK_BYTES], compressed[SWAPZ_MAX_COMPRESSED];
        initialize(); fill_original(page, 9U);
        int length = encode(page, compressed);
        int index = reserve_import(0U, 1U, 1U, page, compressed, (unsigned int)length);
        CHECK(index >= 0, "oracle_setup");
        CHECK(complete_write(0U, (unsigned int)index, 1U, true, true, false) == 0, "oracle_first");
        unsigned int pinned;
        CHECK(pin_read(0U, &pinned) == 0, "oracle_pin");
        state.maps[0].valid = false; /* Simulated overwrite while old reader is held. */
        CHECK(retire((unsigned int)index) == -EBUSY, "decoder_pinned");
        unpin_read(pinned);
    } else if (!strcmp(name, "crc")) {
        uint8_t page[SWAPZ_BLOCK_BYTES], compressed[SWAPZ_MAX_COMPRESSED], output[SWAPZ_BLOCK_BYTES];
        initialize(); fill_original(page, 9U);
        int length = encode(page, compressed);
        int index = reserve_import(0U, 1U, 1U, page, compressed, (unsigned int)length);
        CHECK(index >= 0, "oracle_setup");
        CHECK(complete_write(0U, (unsigned int)index, 1U, true, true, false) == 0, "oracle_first");
        unsigned int pinned;
        CHECK(pin_read(0U, &pinned) == 0, "oracle_pin");
        state.entries[index].compressed_crc ^= 1U; /* Metadata-only corruption. */
        CHECK(decode_pinned(pinned, output) == -EBADMSG, "corruption_no_raw_fallback");
        unpin_read(pinned);
    } else if (!strcmp(name, "gc")) {
        uint8_t page[SWAPZ_BLOCK_BYTES], compressed[SWAPZ_MAX_COMPRESSED];
        initialize(); fill_original(page, 9U);
        int length = encode(page, compressed);
        int index = reserve_import(0U, 1U, 1U, page, compressed, (unsigned int)length);
        CHECK(index >= 0, "oracle_setup");
        CHECK(complete_write(0U, (unsigned int)index, 1U, true, true, false) == 0, "oracle_first");
        CHECK(relocate_gc(0U, 12U, true, false, true) == -EAGAIN, "gc_durable");
    } else if (!strcmp(name, "tag")) {
        uint8_t page[SWAPZ_BLOCK_BYTES], compressed[SWAPZ_MAX_COMPRESSED];
        initialize(); fill_original(page, 9U);
        int length = encode(page, compressed);
        int index = reserve_import(0U, 1U, 1U, page, compressed, (unsigned int)length);
        CHECK(index >= 0, "oracle_setup");
        CHECK(complete_write(0U, (unsigned int)index, 1U, true, true, false) == 0, "oracle_first");
        state.entries[index].representation = 0U;
        unsigned int pinned;
        CHECK(pin_read(0U, &pinned) == -ESTALE, "import_tag_required");
    } else {
        return 2;
    }
    return 0;
}

int main(int argc, char **argv)
{
    if (argc == 2)
        return oracle(argv[1]);
    if (argc != 1)
        return 2;
    CHECK(test_lifecycle() == 0, "lifecycle");
    CHECK(test_resource_bounds() == 0, "resource_bounds");
    CHECK(SOURCE_MAPPED_AUTHENTICATED == 0 &&
          DIRECT_COMPRESSED_HANDOFF == 0 && FORCED_RAW_BYPASS == 0, "auth_disabled");
    printf("PASS lifecycle=%u bounds=%u descriptor_bytes=%zu map_bytes=%zu "
           "live_limit=%u staging_limit=%u NOT_AUTH=1 PHASE_A=BLOCKED\n",
           cases, rejects, sizeof(descriptor), sizeof(mapping),
           (unsigned int)DESCRIPTORS, (unsigned int)MAX_STAGING);
    return 0;
}
