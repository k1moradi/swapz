/* SPDX-License-Identifier: GPL-2.0-only */
/* Rootless deterministic MODEL only: NOT an original MM event producer or DM IO. */
#include <errno.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>

#include "../../../../src/kernel/codec.h"

enum { DISK_BLOCKS = 64, MAX_QUEUE = 8, MAX_LIVE = 32,
       MAX_EXTENTS = 64, MAX_TICKETS = 2048, MAX_PACK = 4 };
enum { CODEC_LZ4 = 1, CODEC_OTHER = 2, FRAME_RAW = 1, FRAME_WRAPPED = 2 };
#define SOURCE_MAPPED_AUTHENTICATED 0
#define DIRECT_COMPRESSED_HANDOFF 0
#define FORCED_RAW_BYPASS 0

struct event {
    uint64_t event_id;
    uint64_t source_sector;
    uint64_t target_relative_sector;
    uint32_t swap_type;
    uint32_t swap_offset;
    uint32_t slot_incarnation;
    uint32_t observed_incarnation;
    uint32_t gc_epoch;
    uint32_t target_epoch;
    uint16_t stored_length;
    uint16_t swapz_length;
    uint8_t codec;
    uint8_t framing;
    bool native_mm_eviction;
    bool source_counted_lease;
    bool current_target_lease;
    bool codec_verified;
    bool crc_verified;
    bool decoded_sha_verified;
    bool correct_backing_device;
    bool correct_target_sector;
    bool lower_durable;
    bool cancelled_by_swapoff;
    bool cancelled_by_dtr;
    bool inject_eio;
    uint8_t original[SWAPZ_BLOCK_BYTES];
};

struct extent {
    uint32_t start_block;
    uint16_t payload_bytes;
    uint8_t blocks;
    uint8_t live_records;
    bool occupied;
};

struct mapping {
    uint64_t original_hash;
    uint32_t generation;
    uint32_t extent_index;
    uint16_t offset;
    uint16_t length;
    bool live;
    bool raw;
};

struct model {
    uint8_t disk[DISK_BLOCKS * SWAPZ_BLOCK_BYTES];
    uint8_t protected_header[SWAPZ_BLOCK_BYTES];
    uint8_t partition_table[64];
    bool allocated[DISK_BLOCKS];
    struct extent extents[MAX_EXTENTS];
    struct mapping mappings[MAX_LIVE];
    struct event pending[MAX_QUEUE];
    bool acknowledged[MAX_TICKETS];
    uint8_t queue_count;
    uint8_t disk_capacity_blocks;
    uint32_t gc_epoch;
    uint32_t target_epoch;
    uint64_t acknowledged_count;
    uint64_t lower_requests;
    uint64_t lower_bytes;
    uint64_t padding_bytes;
    uint64_t original_decompress_calls;
    uint64_t swapz_compress_calls;
    uint64_t upper_bytes;
    uint64_t last_completed_id;
    bool extent_class_seen[3];
    bool accepting;
};

static struct model state;
static unsigned int cases;
static unsigned int hostile_cases;

#define REQUIRE(condition) do { \
    if (!(condition)) { \
        fprintf(stderr, "FIRST_ERROR line=%d check=%s\n", __LINE__, #condition); \
        return 1; \
    } \
} while (0)

static uint64_t page_identity(const uint8_t *bytes)
{
    uint64_t hash = UINT64_C(14695981039346656037);
    for (size_t index = 0; index < SWAPZ_BLOCK_BYTES; ++index) {
        hash ^= bytes[index];
        hash *= UINT64_C(1099511628211);
    }
    return hash;
}

static void reset_model(uint8_t capacity_blocks)
{
    memset(&state, 0, sizeof(state));
    state.disk_capacity_blocks = capacity_blocks;
    state.target_epoch = 1;
    state.gc_epoch = 1;
    state.accepting = true;
    state.allocated[0] = true; /* Entire physical first page is unavailable. */
    for (size_t index = 0; index < SWAPZ_BLOCK_BYTES; ++index)
        state.disk[index] = (uint8_t)(index * 37U + 0x53U);
    memcpy(state.protected_header, state.disk, SWAPZ_BLOCK_BYTES);
    for (size_t index = 0; index < sizeof(state.partition_table); ++index)
        state.partition_table[index] = (uint8_t)(index ^ 0xa5U);
}

static bool header_untouched(void)
{
    if (memcmp(state.disk, state.protected_header, SWAPZ_BLOCK_BYTES) != 0)
        return false;
    for (size_t index = 0; index < sizeof(state.partition_table); ++index)
        if (state.partition_table[index] != (uint8_t)(index ^ 0xa5U))
            return false;
    return state.allocated[0];
}

static struct event make_event(uint64_t event_id, uint32_t logical,
                               uint16_t swapz_length)
{
    struct event result = {0};
    result.event_id = event_id;
    result.swap_type = 1;
    result.swap_offset = logical;
    result.source_sector = (uint64_t)logical * 8U + 8U;
    result.target_relative_sector = (uint64_t)logical * 8U;
    result.slot_incarnation = (uint32_t)event_id + 1U;
    result.observed_incarnation = result.slot_incarnation;
    result.gc_epoch = state.gc_epoch;
    result.target_epoch = state.target_epoch;
    result.stored_length = 1500;
    result.swapz_length = swapz_length;
    result.codec = CODEC_OTHER; /* Unknown/incompatible original by default. */
    result.framing = FRAME_WRAPPED;
    result.native_mm_eviction = true;
    result.correct_backing_device = true;
    result.correct_target_sector = true;
    for (size_t index = 0; index < sizeof(result.original); ++index)
        result.original[index] = (uint8_t)(event_id * 17U + index * 31U);
    return result;
}

/* Future-only thought experiment; never grants a real counted source or DM ref. */
static bool hypothetical_lower_eligible(const struct event *event)
{
    return event->native_mm_eviction && event->source_counted_lease &&
        event->current_target_lease && event->codec_verified &&
        event->crc_verified && event->decoded_sha_verified &&
        event->codec == CODEC_LZ4 && event->framing == FRAME_RAW &&
        event->stored_length > 0U &&
        event->stored_length <= SWAPZ_MAX_COMPRESSED &&
        event->correct_backing_device && event->correct_target_sector &&
        event->source_sector >= 8U &&
        (event->target_relative_sector % 8U) == 0U &&
        event->slot_incarnation == event->observed_incarnation &&
        event->target_epoch == state.target_epoch &&
        event->gc_epoch == state.gc_epoch && event->lower_durable &&
        !event->cancelled_by_swapoff && !event->cancelled_by_dtr;
}

/* The CURRENT product path always delivers 4096 uncompressed upper bytes. */
static uint16_t current_upper_raw_bytes(const struct event *event)
{
    (void)event;
    return SWAPZ_BLOCK_BYTES;
}

static int submit_native_event(const struct event *event)
{
    if (!event || !event->native_mm_eviction)
        return -EPERM; /* No synthetic pressure trigger API. */
    if (!state.accepting || event->cancelled_by_dtr)
        return -ESHUTDOWN;
    if (event->cancelled_by_swapoff)
        return -ECANCELED;
    if (event->event_id >= MAX_TICKETS || event->swap_offset >= MAX_LIVE)
        return -EINVAL;
    if (state.queue_count == MAX_QUEUE)
        return -EAGAIN; /* No unbounded wait or hidden source-slot ref. */
    state.pending[state.queue_count++] = *event;
    return 0;
}

static void release_extent_if_unused(uint32_t extent_index)
{
    struct extent *extent = &state.extents[extent_index];
    if (extent->occupied && extent->live_records == 0U) {
        for (uint32_t offset = 0; offset < extent->blocks; ++offset)
            state.allocated[extent->start_block + offset] = false;
        extent->occupied = false;
    }
}

static void acknowledge_one(const struct event *event)
{
    if (!state.acknowledged[event->event_id]) {
        state.acknowledged[event->event_id] = true;
        ++state.acknowledged_count;
        state.last_completed_id = event->event_id;
    }
}

static void remove_pending(uint8_t count)
{
    const size_t remaining = (size_t)(state.queue_count - count);
    memmove(&state.pending[0], &state.pending[count],
            remaining * sizeof(state.pending[0]));
    state.queue_count -= count;
}

static int allocate_extent(uint8_t blocks, uint32_t *extent_index)
{
    uint32_t slot = MAX_EXTENTS;
    uint32_t start;
    for (uint32_t index = 0; index < MAX_EXTENTS; ++index)
        if (!state.extents[index].occupied) {
            slot = index;
            break;
        }
    if (slot == MAX_EXTENTS)
        return -ENOSPC;
    for (start = 1; start + blocks <= state.disk_capacity_blocks; ++start) {
        uint32_t offset = 0;
        for (; offset < blocks; ++offset)
            if (state.allocated[start + offset])
                break;
        if (offset == blocks)
            break;
    }
    if (start + blocks > state.disk_capacity_blocks)
        return -ENOSPC;
    for (uint32_t offset = 0; offset < blocks; ++offset)
        state.allocated[start + offset] = true;
    state.extents[slot] = (struct extent){ .start_block = start,
        .blocks = blocks, .occupied = true };
    *extent_index = slot;
    return 0;
}

static bool mapping_payload_matches(uint32_t logical, const struct event *event)
{
    const struct mapping *record = &state.mappings[logical];
    if (!record->live || record->original_hash != page_identity(event->original))
        return false;
    const struct extent *extent = &state.extents[record->extent_index];
    if (!extent->occupied || record->offset + record->length >
        (uint32_t)extent->blocks * SWAPZ_BLOCK_BYTES)
        return false;
    const uint8_t *payload = &state.disk[(size_t)extent->start_block * SWAPZ_BLOCK_BYTES] + record->offset;
    /* Compressed synthetic bytes are opaque: NO claimed full-page decoder. */
    return memcmp(payload, event->original, record->length) == 0;
}

/*
 * RAW_4096 model readback requires every ORIGINAL uncompressed byte, not
 * just a matching identity hash or a compressed payload prefix.
 */
static bool mapping_full_raw_matches(uint32_t logical, const struct event *event)
{
    const struct mapping *record = &state.mappings[logical];
    if (!record->live || !record->raw || record->length != SWAPZ_BLOCK_BYTES ||
        record->original_hash != page_identity(event->original) ||
        record->extent_index >= MAX_EXTENTS)
        return false;
    const struct extent *extent = &state.extents[record->extent_index];
    if (!extent->occupied ||
        (uint32_t)record->offset + SWAPZ_BLOCK_BYTES >
            (uint32_t)extent->blocks * SWAPZ_BLOCK_BYTES)
        return false;
    const uint8_t *payload =
        &state.disk[(size_t)extent->start_block * SWAPZ_BLOCK_BYTES +
                    record->offset];
    return memcmp(payload, event->original, SWAPZ_BLOCK_BYTES) == 0;
}

static int service_one_pack(bool inject_lower_eio)
{
    if (!state.queue_count)
        return -ENOENT;
    const struct event *first = &state.pending[0];
    if (first->cancelled_by_swapoff || first->cancelled_by_dtr ||
        first->gc_epoch != state.gc_epoch ||
        first->target_epoch != state.target_epoch ||
        first->slot_incarnation != first->observed_incarnation ||
        !first->correct_backing_device || !first->correct_target_sector) {
        acknowledge_one(first); /* Simulated accepted upper failure exactly once. */
        remove_pending(1);
        return -ECANCELED;
    }
    const bool raw = first->swapz_length == 0U ||
                     first->swapz_length > SWAPZ_MAX_COMPRESSED;
    uint8_t take = 1;
    uint32_t payload_bytes = raw ? SWAPZ_BLOCK_BYTES : first->swapz_length;
    if (!raw) {
        while (take < state.queue_count && take < MAX_PACK) {
            const struct event *next = &state.pending[take];
            if (next->swapz_length == 0U ||
                next->swapz_length > SWAPZ_MAX_COMPRESSED ||
                next->cancelled_by_swapoff || next->cancelled_by_dtr ||
                next->inject_eio ||
                next->slot_incarnation != next->observed_incarnation ||
                !next->correct_backing_device ||
                !next->correct_target_sector ||
                next->gc_epoch != state.gc_epoch ||
                next->target_epoch != state.target_epoch ||
                payload_bytes + next->swapz_length > SWAPZ_MAX_EXTENT_BYTES)
                break;
            payload_bytes += next->swapz_length;
            ++take;
        }
    }
    const uint8_t blocks = payload_bytes <= SWAPZ_BLOCK_BYTES ? 1U :
                           payload_bytes <= 2U * SWAPZ_BLOCK_BYTES ? 2U : 4U;
    const uint32_t padded_bytes = (uint32_t)blocks * SWAPZ_BLOCK_BYTES;
    state.extent_class_seen[blocks == 1U ? 0U : blocks == 2U ? 1U : 2U] = true;
    for (uint8_t index = 0; index < take; ++index) {
        ++state.original_decompress_calls; /* Model invokes original decode. */
        ++state.swapz_compress_calls; /* Independent swapz preparation. */
        state.upper_bytes += current_upper_raw_bytes(&state.pending[index]);
    }
    ++state.lower_requests; /* Attempted, not necessarily completed I/O. */
    uint32_t extent_index = 0;
    if (inject_lower_eio || first->inject_eio ||
        allocate_extent(blocks, &extent_index) != 0) {
        for (uint8_t index = 0; index < take; ++index)
            acknowledge_one(&state.pending[index]);
        remove_pending(take);
        return inject_lower_eio || first->inject_eio ? -EIO : -ENOSPC;
    }
    struct extent *extent = &state.extents[extent_index];
    uint8_t *destination = &state.disk[(size_t)extent->start_block * SWAPZ_BLOCK_BYTES];
    memset(destination, 0, padded_bytes); /* Data-only lower extent. */
    uint32_t cursor = 0;
    for (uint8_t index = 0; index < take; ++index) {
        const struct event *event = &state.pending[index];
        const uint16_t length = event->swapz_length == 0U ||
            event->swapz_length > SWAPZ_MAX_COMPRESSED ?
            SWAPZ_BLOCK_BYTES : event->swapz_length;
        memcpy(destination + cursor, event->original, length);
        cursor += length;
    }
    /* Simulated confirmed successful lower completion precedes RAM map/ACK. */
    cursor = 0;
    for (uint8_t index = 0; index < take; ++index) {
        const struct event *event = &state.pending[index];
        struct mapping *record = &state.mappings[event->swap_offset];
        if (record->live) {
            struct extent *previous = &state.extents[record->extent_index];
            --previous->live_records;
            release_extent_if_unused(record->extent_index);
        }
        const uint16_t length = event->swapz_length == 0U ||
            event->swapz_length > SWAPZ_MAX_COMPRESSED ?
            SWAPZ_BLOCK_BYTES : event->swapz_length;
        *record = (struct mapping){ .original_hash = page_identity(event->original),
            .generation = event->slot_incarnation, .extent_index = extent_index,
            .offset = (uint16_t)cursor, .length = length,
            .live = true, .raw = length == SWAPZ_BLOCK_BYTES };
        ++extent->live_records;
        cursor += length;
        acknowledge_one(event);
    }
    extent->payload_bytes = (uint16_t)payload_bytes;
    state.lower_bytes += padded_bytes;
    state.padding_bytes += padded_bytes - payload_bytes;
    remove_pending(take);
    return 0;
}

static int move_live_extent(uint32_t original_index)
{
    struct extent original = state.extents[original_index];
    if (!original.occupied || !original.live_records)
        return -EINVAL;
    uint32_t replacement_index;
    const int allocation = allocate_extent(original.blocks, &replacement_index);
    if (allocation)
        return allocation;
    struct extent *replacement = &state.extents[replacement_index];
    memcpy(&state.disk[(size_t)replacement->start_block * SWAPZ_BLOCK_BYTES],
           &state.disk[(size_t)original.start_block * SWAPZ_BLOCK_BYTES],
           (size_t)original.blocks * SWAPZ_BLOCK_BYTES);
    replacement->payload_bytes = original.payload_bytes;
    replacement->live_records = original.live_records;
    for (uint32_t index = 0; index < MAX_LIVE; ++index)
        if (state.mappings[index].live &&
            state.mappings[index].extent_index == original_index)
            state.mappings[index].extent_index = replacement_index;
    state.extents[original_index].live_records = 0;
    release_extent_if_unused(original_index);
    ++state.gc_epoch;
    state.lower_bytes += (uint32_t)original.blocks * SWAPZ_BLOCK_BYTES;
    ++state.lower_requests;
    return 0;
}

static int test_hostile_future_gates(void)
{
    reset_model(DISK_BLOCKS);
    struct event eligible = make_event(900, 3, 1200);
    eligible.codec = CODEC_LZ4;
    eligible.framing = FRAME_RAW;
    eligible.source_counted_lease = true;
    eligible.current_target_lease = true;
    eligible.codec_verified = true;
    eligible.crc_verified = true;
    eligible.decoded_sha_verified = true;
    eligible.lower_durable = true;
    REQUIRE(hypothetical_lower_eligible(&eligible));
    REQUIRE(SOURCE_MAPPED_AUTHENTICATED == 0 && DIRECT_COMPRESSED_HANDOFF == 0);
    REQUIRE(FORCED_RAW_BYPASS == 0 && current_upper_raw_bytes(&eligible) == 4096U);
#define DENY_MUTATION(statement) do { \
    struct event denied = eligible; \
    statement; \
    REQUIRE(!hypothetical_lower_eligible(&denied)); \
    REQUIRE(current_upper_raw_bytes(&denied) == 4096U); \
    ++hostile_cases; \
} while (0)
    DENY_MUTATION(denied.source_counted_lease = false);
    DENY_MUTATION(denied.current_target_lease = false);
    DENY_MUTATION(denied.codec_verified = false);
    DENY_MUTATION(denied.crc_verified = false);
    DENY_MUTATION(denied.decoded_sha_verified = false);
    DENY_MUTATION(denied.codec = CODEC_OTHER);
    DENY_MUTATION(denied.framing = FRAME_WRAPPED);
    DENY_MUTATION(denied.stored_length = 3569);
    DENY_MUTATION(denied.stored_length = 0);
    DENY_MUTATION(denied.observed_incarnation++);
    DENY_MUTATION(denied.correct_backing_device = false);
    DENY_MUTATION(denied.correct_target_sector = false);
    DENY_MUTATION(denied.target_relative_sector++);
    DENY_MUTATION(denied.gc_epoch++);
    DENY_MUTATION(denied.target_epoch++);
    DENY_MUTATION(denied.lower_durable = false);
    DENY_MUTATION(denied.cancelled_by_swapoff = true);
    DENY_MUTATION(denied.cancelled_by_dtr = true);
    DENY_MUTATION(denied.native_mm_eviction = false);
#undef DENY_MUTATION
    REQUIRE(header_untouched());
    return 0;
}

static int test_stream(uint8_t capacity_blocks, uint64_t first_id)
{
    reset_model(capacity_blocks);
    for (uint64_t iteration = 0; iteration < 64; ++iteration) {
        const uint16_t length = iteration % 7U == 0U ? 4096U :
            iteration % 11U == 0U ? 3569U :
            (uint16_t)(500U + (iteration * 211U) % 3000U);
        struct event event = make_event(first_id + iteration,
                                        (uint32_t)(iteration % 24U), length);
        REQUIRE(!submit_native_event(&event));
        ++cases;
        if (state.queue_count >= 4U) {
            const int outcome = service_one_pack(false);
            REQUIRE(outcome == 0 || outcome == -ENOSPC);
        }
        REQUIRE(header_untouched());
    }
    while (state.queue_count) {
        const int outcome = service_one_pack(false);
        REQUIRE(outcome == 0 || outcome == -ENOSPC);
    }
    REQUIRE(state.acknowledged_count == 64U);
    REQUIRE(state.extent_class_seen[0] && state.extent_class_seen[1] &&
            state.extent_class_seen[2]);
    REQUIRE(state.lower_bytes % SWAPZ_BLOCK_BYTES == 0U);
    REQUIRE(state.padding_bytes <= state.lower_bytes);
    REQUIRE(state.original_decompress_calls == 64U);
    REQUIRE(state.swapz_compress_calls == 64U);
    REQUIRE(state.upper_bytes == 64U * SWAPZ_BLOCK_BYTES);
    REQUIRE(header_untouched());
    return 0;
}

static int test_lifecycle_and_gc(void)
{
    reset_model(32);
    struct event raw_original = make_event(290, 20, 4096);
    REQUIRE(!submit_native_event(&raw_original));
    REQUIRE(!service_one_pack(false));
    REQUIRE(state.mappings[20].raw);
    REQUIRE(state.mappings[20].length == SWAPZ_BLOCK_BYTES);
    REQUIRE(mapping_payload_matches(20, &raw_original));
    REQUIRE(header_untouched());
    for (uint64_t index = 0; index < MAX_QUEUE; ++index) {
        struct event event = make_event(300 + index, (uint32_t)index, 1100);
        REQUIRE(!submit_native_event(&event));
    }
    struct event overflow = make_event(308, 9, 1100);
    REQUIRE(submit_native_event(&overflow) == -EAGAIN);
    REQUIRE(!state.acknowledged[overflow.event_id]);
    REQUIRE(state.queue_count == MAX_QUEUE);
    REQUIRE(!service_one_pack(false));
    REQUIRE(state.acknowledged_count == 5U);
    struct event old = make_event(300, 0, 1100);
    REQUIRE(mapping_payload_matches(0, &old));
    const uint32_t first_extent = state.mappings[0].extent_index;
    REQUIRE(!move_live_extent(first_extent));
    REQUIRE(mapping_payload_matches(0, &old));
    struct event bad = make_event(500, 0, 600);
    REQUIRE(!submit_native_event(&bad));
    while (state.queue_count > 1U) {
        const int outcome = service_one_pack(false);
        REQUIRE(outcome == 0 || outcome == -ECANCELED);
    }
    const uint64_t bytes_before_error = state.lower_bytes;
    REQUIRE(service_one_pack(true) == -EIO);
    REQUIRE(state.lower_bytes == bytes_before_error);
    REQUIRE(mapping_payload_matches(0, &old));
    REQUIRE(state.acknowledged[bad.event_id]);
    const uint64_t ack_count = state.acknowledged_count;
    acknowledge_one(&bad); /* Duplicate delayed completion cannot ACK twice. */
    REQUIRE(state.acknowledged_count == ack_count);
    struct event stale = make_event(501, 1, 1200);
    stale.gc_epoch--;
    REQUIRE(!submit_native_event(&stale));
    REQUIRE(service_one_pack(false) == -ECANCELED);
    REQUIRE(mapping_payload_matches(0, &old));
    struct event cancel = make_event(502, 2, 1200);
    cancel.cancelled_by_swapoff = true;
    REQUIRE(submit_native_event(&cancel) == -ECANCELED);
    REQUIRE(!state.acknowledged[cancel.event_id]);
    struct event false_origin = make_event(503, 2, 1200);
    false_origin.native_mm_eviction = false;
    REQUIRE(submit_native_event(&false_origin) == -EPERM);
    struct event pending = make_event(504, 2, 1200);
    REQUIRE(!submit_native_event(&pending));
    state.accepting = false; /* Synthetic dtr closes admission, then drains. */
    state.pending[0].cancelled_by_dtr = true;
    REQUIRE(service_one_pack(false) == -ECANCELED);
    REQUIRE(state.acknowledged[pending.event_id]);
    REQUIRE(submit_native_event(&pending) == -ESHUTDOWN);
    REQUIRE(state.queue_count == 0U && header_untouched());
    return 0;
}

/*
 * A rejected admission owns no upper ACK; a failed accepted rewrite does
 * receive one error ACK but must not supersede the last durable map. Later
 * GC movement, stale slot mutation and a full-byte RAW retry retain that
 * ordering without ever initiating native Linux MM reclaim.
 */
static int test_full_raw_retry_after_backpressure_and_rollback(void)
{
    reset_model(32);
    struct event committed = make_event(1000, 5, SWAPZ_BLOCK_BYTES);
    REQUIRE(!submit_native_event(&committed));
    REQUIRE(!service_one_pack(false));
    REQUIRE(mapping_full_raw_matches(5, &committed));
    const uint32_t committed_generation = state.mappings[5].generation;

    struct event rejected = make_event(1050, 5, SWAPZ_BLOCK_BYTES);
    rejected.original[0] ^= 0xa5U;
    rejected.original[SWAPZ_BLOCK_BYTES - 1U] ^= 0x5aU;
    for (uint64_t index = 0; index < MAX_QUEUE; ++index) {
        struct event neighbor = make_event(1010 + index,
                                           (uint32_t)index + 8U,
                                           SWAPZ_BLOCK_BYTES);
        REQUIRE(!submit_native_event(&neighbor));
    }
    REQUIRE(state.queue_count == MAX_QUEUE);
    REQUIRE(submit_native_event(&rejected) == -EAGAIN);
    REQUIRE(!state.acknowledged[rejected.event_id]);
    REQUIRE(state.mappings[5].generation == committed_generation);
    REQUIRE(mapping_full_raw_matches(5, &committed));
    while (state.queue_count)
        REQUIRE(!service_one_pack(false));

    struct event failed_rewrite = make_event(1051, 5, SWAPZ_BLOCK_BYTES);
    memcpy(failed_rewrite.original, rejected.original, SWAPZ_BLOCK_BYTES);
    const uint64_t durable_bytes = state.lower_bytes;
    const uint64_t upper_bytes = state.upper_bytes;
    REQUIRE(!submit_native_event(&failed_rewrite));
    REQUIRE(service_one_pack(true) == -EIO);
    REQUIRE(state.acknowledged[failed_rewrite.event_id]);
    REQUIRE(state.lower_bytes == durable_bytes);
    REQUIRE(state.upper_bytes == upper_bytes + SWAPZ_BLOCK_BYTES);
    REQUIRE(state.mappings[5].generation == committed_generation);
    REQUIRE(mapping_full_raw_matches(5, &committed));

    const uint32_t previous_extent = state.mappings[5].extent_index;
    REQUIRE(!move_live_extent(previous_extent));
    REQUIRE(mapping_full_raw_matches(5, &committed));
    struct event stale_gc = failed_rewrite;
    stale_gc.event_id = 1052;
    REQUIRE(!submit_native_event(&stale_gc));
    REQUIRE(service_one_pack(false) == -ECANCELED);
    REQUIRE(mapping_full_raw_matches(5, &committed));
    ++hostile_cases; /* Changed GC generation cannot publish an old rewrite. */

    struct event recycled_slot = make_event(1053, 5, SWAPZ_BLOCK_BYTES);
    recycled_slot.observed_incarnation++;
    REQUIRE(!submit_native_event(&recycled_slot));
    REQUIRE(service_one_pack(false) == -ECANCELED);
    REQUIRE(mapping_full_raw_matches(5, &committed));
    ++hostile_cases; /* Recycled slot ABA cannot publish stale upper bytes. */

    struct event valid_retry = make_event(1054, 5, SWAPZ_BLOCK_BYTES);
    memcpy(valid_retry.original, failed_rewrite.original, SWAPZ_BLOCK_BYTES);
    REQUIRE(memcmp(valid_retry.original, committed.original,
                   SWAPZ_BLOCK_BYTES) != 0);
    REQUIRE(current_upper_raw_bytes(&valid_retry) == SWAPZ_BLOCK_BYTES);
    REQUIRE(!submit_native_event(&valid_retry));
    REQUIRE(!service_one_pack(false));
    REQUIRE(mapping_full_raw_matches(5, &valid_retry));
    REQUIRE(!mapping_full_raw_matches(5, &committed));
    REQUIRE(state.mappings[5].generation == valid_retry.slot_incarnation);
    const uint64_t unique_ack_count = state.acknowledged_count;
    acknowledge_one(&valid_retry); /* Late duplicate completion is inert. */
    REQUIRE(state.acknowledged_count == unique_ack_count);
    REQUIRE(state.queue_count == 0U && header_untouched());
    return 0;
}

int main(void)
{
    if (test_hostile_future_gates() ||
        test_stream(16, 0) || test_stream(32, 64) ||
        test_stream(64, 128) || test_lifecycle_and_gc() ||
        test_full_raw_retry_after_backpressure_and_rollback())
        return 1;
    if (cases < 120U || hostile_cases < 10U) {
        fprintf(stderr, "FIRST_ERROR insufficient deterministic cases\n");
        return 1;
    }
    printf("PASS events=%u hostile=%u capacity_blocks=16,32,64 "
           "NOT_AUTH=1 PHASE_A=BLOCKED synthetic_only=1\n",
           cases, hostile_cases);
    return 0;
}
