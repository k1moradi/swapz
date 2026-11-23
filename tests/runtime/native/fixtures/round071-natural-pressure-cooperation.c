/* SPDX-License-Identifier: GPL-2.0-only */
/*
 * Round071 rootless cooperative scheduling CONTRACT MODEL. This fixture does
 * not invoke original Linux MM, zswap, DM, a lower device or real pressure.
 * The two production headers below provide the dormant codec/extent ABI and
 * gates; no product source is modified or made active by this program.
 */
#include <errno.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>

#define SWAPZ_ZSWAP_IMPORT_HOST_TEST 1
#define SOURCE_MAPPED_AUTHENTICATED 0
#define DIRECT_COMPRESSED_HANDOFF 0
#define FORCED_RAW_BYPASS 0
#include "../../../../src/kernel/zswap-import-codec.h"
#include "../../../../src/kernel/zswap-direct-handoff.h"

enum { MAX_QUEUE = 8, MAX_TICKETS = 128, DISK_BLOCKS = 64,
       MAX_EXTENTS = 64, MAX_OWNED_BYTES = MAX_QUEUE * SWAPZ_MAX_COMPRESSED };

enum payload_kind { ORIGINAL_COMPRESSED, CONVENTIONAL_RAW_4096 };

struct natural_arrival {
    uint32_t ticket;
    uint32_t incarnation;
    uint32_t codec_generation;
    uint32_t observed_codec_generation;
    uint32_t length;
    uint8_t codec;
    enum payload_kind kind;
    bool natural_mm_eviction;
    bool source_live;
    bool codec_retired;
    bool source_lock_held;
    uint8_t bytes[SWAPZ_BLOCK_BYTES];
};

struct pending_copy {
    uint32_t ticket;
    uint32_t incarnation;
    uint32_t codec_generation;
    uint32_t length;
    uint8_t codec;
    enum payload_kind kind;
    uint8_t bytes[SWAPZ_BLOCK_BYTES];
};

struct extent {
    uint32_t first_block;
    uint32_t blocks;
    uint32_t records;
    bool live;
};

struct mapping {
    uint32_t incarnation;
    uint32_t codec_generation;
    uint32_t extent_index;
    uint32_t offset;
    uint32_t length;
    uint8_t codec;
    enum payload_kind kind;
    bool published;
};

struct completion {
    uint32_t count;
    int status;
};

struct cooperative_model {
    uint8_t disk[DISK_BLOCKS * SWAPZ_BLOCK_BYTES];
    uint8_t immutable_header[SWAPZ_BLOCK_BYTES];
    bool allocated[DISK_BLOCKS];
    struct extent extents[MAX_EXTENTS];
    struct mapping mappings[MAX_TICKETS];
    struct completion completions[MAX_TICKETS];
    struct pending_copy queue[MAX_QUEUE];
    uint32_t queue_count;
    uint32_t pending_bytes;
    uint32_t reader_pins;
    uint32_t first_completed_ticket;
    uint32_t last_completed_ticket;
    uint32_t accepted;
    uint32_t completed;
    uint32_t mm_eviction_decisions;
    uint32_t swapz_secondary_reclaim_calls;
    uint32_t swapz_pressure_timer_calls;
    uint32_t decompression_calls;
    uint32_t recompress_calls;
    uint32_t source_copied_bytes;
    uint32_t write_attempts;
    uint32_t fua_completions;
    uint32_t gc_copy_bytes;
    uint32_t lower_bytes;
    uint32_t extent_classes;
    uint32_t peak_pending_bytes;
    uint32_t peak_queue_depth;
    uint32_t fifo_violations;
    int first_error;
    bool mm_lock_held;
    bool worker_lock_held;
    bool closed;
    bool inject_allocation_failure;
};

static struct cooperative_model model;
static uint32_t directed_checks;
static uint32_t burst_events;

#define REQUIRE(condition) do { \
    if (!(condition)) { \
        fprintf(stderr, "FIRST_ERROR line=%d check=%s\n", __LINE__, #condition); \
        return 1; \
    } \
} while (0)

static void reset_model(void)
{
    memset(&model, 0, sizeof(model));
    model.allocated[0] = true; /* Entire SWAPSPACE2 physical header page. */
    for (uint32_t index = 0; index < SWAPZ_BLOCK_BYTES; ++index)
        model.disk[index] = (uint8_t)(index * 23U + 0x51U);
    memcpy(model.immutable_header, model.disk, sizeof(model.immutable_header));
}

static bool no_competing_pressure(void)
{
    return model.swapz_secondary_reclaim_calls == 0U &&
           model.swapz_pressure_timer_calls == 0U &&
           model.decompression_calls == 0U && model.recompress_calls == 0U;
}

static bool header_preserved(void)
{
    return model.allocated[0] &&
           memcmp(model.disk, model.immutable_header,
                  sizeof(model.immutable_header)) == 0;
}

static struct natural_arrival arrival(uint32_t ticket, uint8_t codec,
                                      uint32_t length, enum payload_kind kind)
{
    struct natural_arrival result = {0};
    result.ticket = ticket;
    result.incarnation = ticket + 1U;
    result.codec_generation = 7U;
    result.observed_codec_generation = 7U;
    result.length = length;
    result.codec = codec;
    result.kind = kind;
    result.natural_mm_eviction = true;
    result.source_live = true;
    result.source_lock_held = true; /* Bounded copy under original lease. */
    for (uint32_t index = 0; index < SWAPZ_BLOCK_BYTES; ++index)
        result.bytes[index] = (uint8_t)(ticket * 17U + index * 19U);
    return result;
}

static void record_first_error(int status)
{
    if (status != 0 && model.first_error == 0)
        model.first_error = status;
}

/* Never makes an MM eviction decision: caller is a preselected natural event. */
static int enqueue_owned_copy(const struct natural_arrival *source)
{
    if (!source || !source->natural_mm_eviction)
        return -EPERM;
    ++model.mm_eviction_decisions; /* Exactly one *external* source event. */
    if (model.closed)
        return -ESHUTDOWN;
    if (!source->source_live || source->codec_retired ||
        !source->incarnation || !source->codec_generation ||
        source->codec_generation != source->observed_codec_generation)
        return -ESTALE;
    if (!source->source_lock_held)
        return -EPERM;
    if (source->ticket >= MAX_TICKETS ||
        model.completions[source->ticket].count != 0U)
        return -EINVAL;
    if (source->kind == ORIGINAL_COMPRESSED) {
        if (source->codec != SWAPZ_ZSWAP_IMPORT_LZ4_CODEC &&
            source->codec != SWAPZ_ZSWAP_IMPORT_LZO1X_CODEC)
            return -EOPNOTSUPP;
        if (!source->length || source->length > SWAPZ_MAX_COMPRESSED)
            return -EMSGSIZE;
    } else if (source->kind != CONVENTIONAL_RAW_4096 ||
               source->length != SWAPZ_BLOCK_BYTES || source->codec != 0U) {
        return -EINVAL; /* RAW_4096 is a full *uncompressed* page. */
    }
    for (uint32_t index = 0; index < model.queue_count; ++index)
        if (model.queue[index].ticket == source->ticket)
            return -EALREADY; /* Pending owner, not yet upper-completed. */
    if (model.queue_count == MAX_QUEUE ||
        source->length > MAX_OWNED_BYTES - model.pending_bytes)
        return -EAGAIN; /* Never request further zswap reclaim to make room. */
    struct pending_copy *entry = &model.queue[model.queue_count];
    entry->ticket = source->ticket;
    entry->incarnation = source->incarnation;
    entry->codec_generation = source->codec_generation;
    entry->codec = source->codec;
    entry->kind = source->kind;
    entry->length = source->length;
    memcpy(entry->bytes, source->bytes, source->length);
    model.source_copied_bytes += source->length;
    model.pending_bytes += source->length;
    ++model.queue_count;
    ++model.accepted;
    if (model.queue_count > model.peak_queue_depth)
        model.peak_queue_depth = model.queue_count;
    if (model.pending_bytes > model.peak_pending_bytes)
        model.peak_pending_bytes = model.pending_bytes;
    return 0;
}

static void complete_ticket(uint32_t ticket, int status)
{
    struct completion *completion = &model.completions[ticket];
    if (completion->count == 0U) {
        completion->status = status;
        ++completion->count;
        if (model.completed != 0U && ticket <= model.last_completed_ticket)
            ++model.fifo_violations;
        ++model.completed;
        if (model.completed == 1U)
            model.first_completed_ticket = ticket;
        model.last_completed_ticket = ticket;
        record_first_error(status);
    }
    /* Duplicate lower endio does not overwrite or repeat the upper ACK. */
}

static void consume_queue(uint32_t count)
{
    for (uint32_t index = 0; index < count; ++index)
        model.pending_bytes -= model.queue[index].length;
    model.queue_count -= count;
    memmove(model.queue, model.queue + count,
            (size_t)model.queue_count * sizeof(model.queue[0]));
}

static int allocate_extent(uint32_t blocks, uint32_t *extent_index)
{
    if (model.inject_allocation_failure)
        return -ENOMEM;
    for (uint32_t index = 0; index < MAX_EXTENTS; ++index) {
        if (model.extents[index].live)
            continue;
        for (uint32_t first = 1; first + blocks <= DISK_BLOCKS; ++first) {
            uint32_t count = 0;
            for (; count < blocks; ++count)
                if (model.allocated[first + count])
                    break;
            if (count != blocks)
                continue;
            for (uint32_t block = 0; block < blocks; ++block)
                model.allocated[first + block] = true;
            model.extents[index] = (struct extent){
                .first_block = first, .blocks = blocks, .live = true };
            *extent_index = index;
            return 0;
        }
    }
    return -ENOSPC;
}

/* Worker runs outside ALL MM/queue locks. Durable FUA precedes publication. */
static int service_fifo(int lower_status, bool durable_fua)
{
    if (model.worker_lock_held || model.mm_lock_held)
        return -EDEADLK;
    if (!model.queue_count)
        return -ENOENT;
    uint32_t count = 1U;
    uint32_t payload_bytes = model.queue[0].length;
    while (count < model.queue_count &&
           payload_bytes + model.queue[count].length <= SWAPZ_MAX_EXTENT_BYTES) {
        payload_bytes += model.queue[count].length;
        ++count;
    }
    const uint32_t blocks = payload_bytes <= SWAPZ_BLOCK_BYTES ? 1U :
        payload_bytes <= 2U * SWAPZ_BLOCK_BYTES ? 2U : 4U;
    ++model.write_attempts;
    if (lower_status != 0 || !durable_fua) {
        const int status = lower_status != 0 ? lower_status : -EIO;
        for (uint32_t index = 0; index < count; ++index)
            complete_ticket(model.queue[index].ticket, status);
        consume_queue(count);
        return status;
    }
    uint32_t extent_index = 0;
    const int allocation_status = allocate_extent(blocks, &extent_index);
    if (allocation_status != 0) {
        for (uint32_t index = 0; index < count; ++index)
            complete_ticket(model.queue[index].ticket, allocation_status);
        consume_queue(count);
        return allocation_status;
    }
    struct extent *extent = &model.extents[extent_index];
    uint8_t *destination = &model.disk[(size_t)extent->first_block * SWAPZ_BLOCK_BYTES];
    const uint32_t padded_bytes = blocks * SWAPZ_BLOCK_BYTES;
    memset(destination, 0, padded_bytes);
    uint32_t offset = 0;
    for (uint32_t index = 0; index < count; ++index) {
        const struct pending_copy *entry = &model.queue[index];
        memcpy(destination + offset, entry->bytes, entry->length);
        offset += entry->length;
    }
    /* Simulated confirmed ordered lower success, NOT real I/O or durable media. */
    ++model.fua_completions;
    model.lower_bytes += padded_bytes;
    model.extent_classes |= blocks == 1U ? 1U : blocks == 2U ? 2U : 4U;
    offset = 0;
    for (uint32_t index = 0; index < count; ++index) {
        const struct pending_copy *entry = &model.queue[index];
        struct mapping *record = &model.mappings[entry->ticket];
        record->incarnation = entry->incarnation;
        record->codec_generation = entry->codec_generation;
        record->extent_index = extent_index;
        record->offset = offset;
        record->length = entry->length;
        record->codec = entry->codec;
        record->kind = entry->kind;
        record->published = true;
        ++extent->records;
        offset += entry->length;
        complete_ticket(entry->ticket, 0);
    }
    consume_queue(count);
    return 0;
}

static bool mapping_matches(uint32_t ticket, const struct natural_arrival *original)
{
    const struct mapping *record = &model.mappings[ticket];
    if (!record->published || record->incarnation != original->incarnation ||
        record->codec_generation != original->codec_generation ||
        record->codec != original->codec || record->kind != original->kind ||
        record->length != original->length)
        return false;
    if ((record->kind == CONVENTIONAL_RAW_4096 &&
         (record->length != SWAPZ_BLOCK_BYTES || record->codec != 0U)) ||
        (record->kind == ORIGINAL_COMPRESSED &&
         (record->length > SWAPZ_MAX_COMPRESSED ||
          (record->codec != SWAPZ_ZSWAP_IMPORT_LZ4_CODEC &&
           record->codec != SWAPZ_ZSWAP_IMPORT_LZO1X_CODEC))))
        return false;
    if (record->extent_index >= MAX_EXTENTS)
        return false;
    const struct extent *extent = &model.extents[record->extent_index];
    if (!extent->live || record->offset + record->length >
        extent->blocks * SWAPZ_BLOCK_BYTES)
        return false;
    const uint8_t *payload = &model.disk[(size_t)extent->first_block *
                                          SWAPZ_BLOCK_BYTES + record->offset];
    return memcmp(payload, original->bytes, record->length) == 0;
}

/* GC cannot reclaim a live reader's source; after release it copies bytes. */
static int gc_move(uint32_t extent_index)
{
    if (model.reader_pins)
        return -EBUSY;
    if (model.worker_lock_held || model.mm_lock_held)
        return -EDEADLK;
    if (extent_index >= MAX_EXTENTS || !model.extents[extent_index].live)
        return -ENOENT;
    const struct extent old = model.extents[extent_index];
    uint32_t replacement_index = 0;
    const int result = allocate_extent(old.blocks, &replacement_index);
    if (result != 0)
        return result;
    struct extent *replacement = &model.extents[replacement_index];
    memcpy(&model.disk[(size_t)replacement->first_block * SWAPZ_BLOCK_BYTES],
           &model.disk[(size_t)old.first_block * SWAPZ_BLOCK_BYTES],
           (size_t)old.blocks * SWAPZ_BLOCK_BYTES);
    replacement->records = old.records;
    for (uint32_t ticket = 0; ticket < MAX_TICKETS; ++ticket)
        if (model.mappings[ticket].published &&
            model.mappings[ticket].extent_index == extent_index)
            model.mappings[ticket].extent_index = replacement_index;
    for (uint32_t block = 0; block < old.blocks; ++block)
        model.allocated[old.first_block + block] = false;
    model.extents[extent_index] = (struct extent){0};
    model.gc_copy_bytes += old.blocks * SWAPZ_BLOCK_BYTES;
    return 0;
}

static int test_gate_codec_and_lifetime(void)
{
    reset_model();
    REQUIRE(SOURCE_MAPPED_AUTHENTICATED == 0 &&
            DIRECT_COMPRESSED_HANDOFF == 0 && FORCED_RAW_BYPASS == 0);
    REQUIRE(SWAPZ_DIRECT_HANDOFF_PRODUCTION_ENABLED == 0U);
    REQUIRE(SWAPZ_ZSWAP_IMPORT_ACTIVE == 0U);
    REQUIRE(SWAPZ_CODEC_METADATA_ON_MEDIA == 0U);
    REQUIRE(SWAPZ_ZSWAP_IMPORT_REPRESENTATION != SWAPZ_DIRECT_FULL_PAGE);
    REQUIRE(SWAPZ_MAX_EXTENT_BYTES == 4U * SWAPZ_BLOCK_BYTES);
    REQUIRE(SWAPZ_ZSWAP_IMPORT_LZ4_CODEC != SWAPZ_ZSWAP_IMPORT_LZO1X_CODEC);
    for (uint32_t index = 0; index < 2U; ++index) {
        struct natural_arrival source = arrival(index,
            index ? SWAPZ_ZSWAP_IMPORT_LZO1X_CODEC : SWAPZ_ZSWAP_IMPORT_LZ4_CODEC,
            2301U + index, ORIGINAL_COMPRESSED);
        REQUIRE(enqueue_owned_copy(&source) == 0);
        memset(source.bytes, 0xa6, sizeof(source.bytes)); /* Source freed/poisoned. */
        const struct natural_arrival expected = arrival(index,
            index ? SWAPZ_ZSWAP_IMPORT_LZO1X_CODEC : SWAPZ_ZSWAP_IMPORT_LZ4_CODEC,
            2301U + index, ORIGINAL_COMPRESSED);
        REQUIRE(service_fifo(0, true) == 0);
        REQUIRE(mapping_matches(index, &expected));
        REQUIRE(model.completions[index].count == 1U);
        ++directed_checks;
    }
    struct natural_arrival raw = arrival(2U, 0U, SWAPZ_BLOCK_BYTES,
                                         CONVENTIONAL_RAW_4096);
    REQUIRE(enqueue_owned_copy(&raw) == 0);
    REQUIRE(service_fifo(0, true) == 0);
    REQUIRE(mapping_matches(2U, &raw));
    REQUIRE(model.mappings[2U].kind == CONVENTIONAL_RAW_4096);
    REQUIRE(model.mappings[2U].length == SWAPZ_BLOCK_BYTES);
    REQUIRE(model.mappings[2U].codec == 0U);
    ++directed_checks;
    const uint32_t selected_extent = model.mappings[1U].extent_index;
    ++model.reader_pins;
    REQUIRE(gc_move(selected_extent) == -EBUSY);
    REQUIRE(mapping_matches(1U, &(struct natural_arrival){0}) == false);
    --model.reader_pins;
    const struct natural_arrival lzo = arrival(1U, SWAPZ_ZSWAP_IMPORT_LZO1X_CODEC,
                                               2302U, ORIGINAL_COMPRESSED);
    REQUIRE(gc_move(selected_extent) == 0);
    REQUIRE(mapping_matches(1U, &lzo));
    REQUIRE(model.gc_copy_bytes >= SWAPZ_BLOCK_BYTES);
    REQUIRE(model.fifo_violations == 0U && no_competing_pressure() &&
            header_preserved());
    ++directed_checks;
    return 0;
}

static int test_denials_backpressure_and_errors(void)
{
    reset_model();
    struct natural_arrival source = arrival(10U, SWAPZ_ZSWAP_IMPORT_LZ4_CODEC,
                                             1400U, ORIGINAL_COMPRESSED);
    source.natural_mm_eviction = false;
    REQUIRE(enqueue_owned_copy(&source) == -EPERM);
    REQUIRE(model.mm_eviction_decisions == 0U);
    source.natural_mm_eviction = true;
    source.source_live = false;
    REQUIRE(enqueue_owned_copy(&source) == -ESTALE);
    source.source_live = true;
    source.codec_retired = true;
    REQUIRE(enqueue_owned_copy(&source) == -ESTALE);
    source.codec_retired = false;
    ++source.observed_codec_generation;
    REQUIRE(enqueue_owned_copy(&source) == -ESTALE);
    --source.observed_codec_generation;
    source.source_lock_held = false;
    REQUIRE(enqueue_owned_copy(&source) == -EPERM);
    source.source_lock_held = true;
    source.length = SWAPZ_MAX_COMPRESSED + 1U;
    REQUIRE(enqueue_owned_copy(&source) == -EMSGSIZE);
    source.length = 1400U;
    source.codec = 0xffU;
    REQUIRE(enqueue_owned_copy(&source) == -EOPNOTSUPP);
    source.codec = SWAPZ_ZSWAP_IMPORT_LZ4_CODEC;
    source.kind = CONVENTIONAL_RAW_4096;
    REQUIRE(enqueue_owned_copy(&source) == -EINVAL);
    source.codec = 0U;
    REQUIRE(enqueue_owned_copy(&source) == -EINVAL); /* No short RAW page. */
    source.codec = SWAPZ_ZSWAP_IMPORT_LZ4_CODEC;
    source.kind = ORIGINAL_COMPRESSED;
    REQUIRE(enqueue_owned_copy(&source) == 0);
    REQUIRE(enqueue_owned_copy(&source) == -EALREADY);
    REQUIRE(model.queue_count == 1U);
    source.ticket = 11U;
    source.incarnation = 12U;
    source.length = 3000U; /* Two FIFO packs, exercising separate lower failures. */
    for (uint32_t index = 1; index < MAX_QUEUE; ++index) {
        source.ticket = 10U + index;
        source.incarnation = source.ticket + 1U;
        REQUIRE(enqueue_owned_copy(&source) == 0);
    }
    const uint32_t bytes_before_overflow = model.source_copied_bytes;
    source.ticket = 18U;
    source.incarnation = 19U;
    REQUIRE(enqueue_owned_copy(&source) == -EAGAIN);
    REQUIRE(model.source_copied_bytes == bytes_before_overflow);
    REQUIRE(model.completions[18U].count == 0U);
    REQUIRE(model.queue_count == MAX_QUEUE &&
            model.pending_bytes <= MAX_OWNED_BYTES);
    model.mm_lock_held = true;
    REQUIRE(service_fifo(0, true) == -EDEADLK);
    model.mm_lock_held = false;
    model.worker_lock_held = true;
    REQUIRE(service_fifo(0, true) == -EDEADLK);
    model.worker_lock_held = false;
    REQUIRE(service_fifo(-EIO, true) == -EIO);
    REQUIRE(model.first_error == -EIO);
    REQUIRE(model.fua_completions == 0U);
    REQUIRE(model.completions[10U].count == 1U &&
            model.completions[10U].status == -EIO &&
            !model.mappings[10U].published);
    REQUIRE(service_fifo(0, false) == -EIO);
    REQUIRE(model.first_error == -EIO);
    REQUIRE(model.completions[17U].count == 1U &&
            model.completions[17U].status == -EIO);
    const uint32_t completed_before_duplicate = model.completed;
    complete_ticket(10U, 0);
    REQUIRE(model.completed == completed_before_duplicate);
    REQUIRE(model.completions[10U].status == -EIO);
    REQUIRE(model.queue_count == 0U && model.pending_bytes == 0U);
    reset_model();
    const struct natural_arrival transient = arrival(25U,
        SWAPZ_ZSWAP_IMPORT_LZO1X_CODEC, 2100U, ORIGINAL_COMPRESSED);
    REQUIRE(enqueue_owned_copy(&transient) == 0);
    model.inject_allocation_failure = true;
    REQUIRE(service_fifo(0, true) == -ENOMEM);
    REQUIRE(model.completions[25U].count == 1U &&
            model.completions[25U].status == -ENOMEM &&
            !model.mappings[25U].published);
    REQUIRE(model.first_error == -ENOMEM);
    model.closed = true;
    REQUIRE(enqueue_owned_copy(&transient) == -ESHUTDOWN);
    REQUIRE(model.fua_completions == 0U);
    REQUIRE(model.fifo_violations == 0U && no_competing_pressure() &&
            header_preserved());
    directed_checks += 18U;
    return 0;
}

static int test_bursty_fairness_and_extent_classes(void)
{
    uint32_t seen_classes = 0;
    reset_model();
    for (uint32_t index = 0; index < 2U; ++index) {
        const struct natural_arrival source = arrival(index,
            SWAPZ_ZSWAP_IMPORT_LZ4_CODEC, 3000U, ORIGINAL_COMPRESSED);
        REQUIRE(enqueue_owned_copy(&source) == 0);
    }
    REQUIRE(service_fifo(0, true) == 0);
    REQUIRE(model.extent_classes == 2U); /* Exactly 2*3000 -> 8KiB. */
    seen_classes |= model.extent_classes;
    ++directed_checks;
    for (uint32_t round = 0; round < 4U; ++round) {
        reset_model();
        const uint32_t length = round == 0U ? 1400U :
                                round == 1U ? 3000U : 2200U;
        for (uint32_t ticket = 0; ticket < 32U; ticket += MAX_QUEUE) {
            const uint32_t first_expected = ticket;
            for (uint32_t index = 0; index < MAX_QUEUE; ++index) {
                const uint32_t id = ticket + index;
                struct natural_arrival source = arrival(id,
                    index % 2U ? SWAPZ_ZSWAP_IMPORT_LZO1X_CODEC :
                                 SWAPZ_ZSWAP_IMPORT_LZ4_CODEC,
                    length, ORIGINAL_COMPRESSED);
                REQUIRE(enqueue_owned_copy(&source) == 0);
                ++burst_events;
            }
            while (model.queue_count) {
                REQUIRE(service_fifo(0, true) == 0);
                REQUIRE(model.pending_bytes <= MAX_OWNED_BYTES);
            }
            REQUIRE(model.first_completed_ticket == 0U);
            REQUIRE(model.last_completed_ticket == ticket + MAX_QUEUE - 1U);
            for (uint32_t index = first_expected; index < ticket + MAX_QUEUE; ++index) {
                const struct natural_arrival expected = arrival(index,
                    index % 2U ? SWAPZ_ZSWAP_IMPORT_LZO1X_CODEC :
                                 SWAPZ_ZSWAP_IMPORT_LZ4_CODEC,
                    length, ORIGINAL_COMPRESSED);
                REQUIRE(model.completions[index].count == 1U);
                REQUIRE(model.completions[index].status == 0);
                REQUIRE(mapping_matches(index, &expected));
            }
        }
        REQUIRE(model.accepted == 32U && model.completed == 32U);
        REQUIRE(model.mm_eviction_decisions == 32U);
        REQUIRE(model.source_copied_bytes == 32U * length);
        REQUIRE(model.lower_bytes % SWAPZ_BLOCK_BYTES == 0U);
        REQUIRE(no_competing_pressure() && header_preserved());
        seen_classes |= model.extent_classes;
    }
    REQUIRE(seen_classes == 7U); /* Actual padded 4, 8, 16KiB. */
    REQUIRE(model.fifo_violations == 0U && model.peak_queue_depth == MAX_QUEUE);
    REQUIRE(model.peak_pending_bytes <= MAX_OWNED_BYTES);
    directed_checks += 4U;
    return 0;
}

int main(void)
{
    if (test_gate_codec_and_lifetime() != 0 ||
        test_denials_backpressure_and_errors() != 0 ||
        test_bursty_fairness_and_extent_classes() != 0)
        return 1;
    printf("PASS directed=%u burst_events=%u extents=4,8,16KiB "
           "MM_ONLY=1 SECONDARY_RECLAIM=0 RECOMPRESS=0 "
           "RAW_4096=UNCOMPRESSED AUTH=0 PHASE_A=BLOCKED "
           "copy_bytes=%u lower_padded_bytes=%u fua=%u "
           "upper_ack=%u queue_peak=%u owned_peak=%u "
           "synthetic_only=1\n", directed_checks, burst_events,
           model.source_copied_bytes, model.lower_bytes,
           model.fua_completions, model.completed, model.peak_queue_depth,
           model.peak_pending_bytes);
    return 0;
}
