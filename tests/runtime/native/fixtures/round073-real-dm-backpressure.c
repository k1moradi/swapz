/* SPDX-License-Identifier: GPL-2.0-only */
/*
 * Round073 Agent11: rootless source-header-linked scheduling CONTRACT MODEL.
 * Real DM worker/queue sites are audited by the paired verifier, not compiled
 * into this userspace process. No original Linux MM, real zswap eviction,
 * compressed-byte handoff, loaded DM, physical I/O or memory pressure runs.
 * The model receives events AFTER an external natural eviction decision.
 * Ownership: one model thread owns its preallocated ring and completions.
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
#include "../../../../src/kernel/authority.h"
#include "../../../../src/kernel/window-policy.h"
#include "../../../../src/kernel/zswap-import-codec.h"
#include "round073-source-quantum.h"

enum { QUEUE_SLOTS = 16, MAX_EVENTS = 256, PENDING_LIMIT = 32768 };
enum item_kind { ORIGINAL_COMPRESSED, ORIGINAL_RAW_4096, FOREGROUND_WRITE, READ };
struct external_event {
    uint32_t slot;
    uint32_t generation;
    uint32_t observed_generation;
    uint32_t bytes;
    uint8_t codec;
    enum item_kind kind;
    bool natural;
    bool source_lease;
    uint8_t payload[SWAPZ_BLOCK_BYTES];
};
struct owned_item {
    uint32_t slot;
    uint32_t generation;
    uint32_t bytes;
    uint8_t codec;
    enum item_kind kind;
    uint8_t payload[SWAPZ_BLOCK_BYTES];
};
struct completion {
    uint32_t count;
    int status;
};
struct queue_model {
    struct owned_item pending[QUEUE_SLOTS];
    struct completion completions[MAX_EVENTS];
    uint32_t head;
    uint32_t count;
    uint32_t owned_bytes;
    uint32_t peak_bytes;
    uint32_t peak_slots;
    uint32_t completions_count;
    uint32_t read_completed;
    uint32_t secondary_pressure_calls;
    uint32_t recompression_calls;
    int first_error;
    bool lower_busy;
    bool closed;
};
static struct queue_model model;
static unsigned int directed_checks;

#define REQUIRE(condition) do { \
    ++directed_checks; \
    if (!(condition)) { \
        fprintf(stderr, "FIRST_ERROR line=%d invariant=%s\n", __LINE__, #condition); \
        return 1; \
    } \
} while (0)

static void reset_model(void)
{
    memset(&model, 0, sizeof(model));
}

static struct external_event make_event(uint32_t slot, enum item_kind kind,
                                         uint32_t bytes, uint8_t codec)
{
    struct external_event result = {
        .slot = slot, .generation = 7U, .observed_generation = 7U,
        .bytes = bytes, .codec = codec, .kind = kind,
        .natural = true, .source_lease = true
    };
    for (uint32_t index = 0; index < SWAPZ_BLOCK_BYTES; ++index)
        result.payload[index] = (uint8_t)(slot * 7U + index * 11U);
    return result;
}

static bool queue_contains(const struct queue_model *queue, uint32_t slot)
{
    for (uint32_t offset = 0; offset < queue->count; ++offset) {
        const uint32_t index = (queue->head + offset) % QUEUE_SLOTS;
        if (queue->pending[index].slot == slot)
            return true;
    }
    return false;
}

/* Only receives independently selected external events; no MM reclaim API. */
static int admit(struct queue_model *queue, const struct external_event *source)
{
    if (queue->closed)
        return -ESHUTDOWN;
    if (!source || source->slot >= MAX_EVENTS || !source->generation)
        return -EINVAL;
    if (queue_contains(queue, source->slot) ||
        queue->completions[source->slot].count != 0U)
        return -EALREADY;
    if (source->kind == ORIGINAL_COMPRESSED ||
        source->kind == ORIGINAL_RAW_4096) {
        if (!source->natural)
            return -EPERM;
        if (!source->source_lease)
            return -EPERM;
        if (source->generation != source->observed_generation)
            return -ESTALE;
        if (source->kind == ORIGINAL_COMPRESSED) {
            if (source->codec != SWAPZ_ZSWAP_IMPORT_LZ4_CODEC &&
                source->codec != SWAPZ_ZSWAP_IMPORT_LZO1X_CODEC)
                return -EOPNOTSUPP;
            if (source->bytes == 0U || source->bytes > SWAPZ_MAX_COMPRESSED)
                return -EMSGSIZE;
        } else if (source->bytes != SWAPZ_BLOCK_BYTES || source->codec != 0U) {
            return -EINVAL; /* Complete original UNCOMPRESSED RAW page. */
        }
    } else if (source->kind == FOREGROUND_WRITE) {
        if (source->bytes != SWAPZ_BLOCK_BYTES || source->codec != 0U)
            return -EINVAL;
    } else if (source->kind != READ || source->bytes != 0U) {
        return -EINVAL;
    }
    if (queue->count == QUEUE_SLOTS)
        return -EAGAIN;
    if (source->bytes > PENDING_LIMIT - queue->owned_bytes)
        return -EAGAIN;
    const uint32_t tail = (queue->head + queue->count) % QUEUE_SLOTS;
    struct owned_item *destination = &queue->pending[tail];
    destination->slot = source->slot;
    destination->generation = source->generation;
    destination->bytes = source->bytes;
    destination->codec = source->codec;
    destination->kind = source->kind;
    memcpy(destination->payload, source->payload, source->bytes);
    queue->owned_bytes += source->bytes;
    ++queue->count;
    if (queue->count > queue->peak_slots)
        queue->peak_slots = queue->count;
    if (queue->owned_bytes > queue->peak_bytes)
        queue->peak_bytes = queue->owned_bytes;
    return 0;
}

/* This is model service, not dm_io or a real BIO endio callback. */
static int service_next(struct queue_model *queue, int lower_error)
{
    if (!queue->count)
        return -ENOENT;
    struct owned_item *item = &queue->pending[queue->head];
    if (queue->lower_busy && item->kind != READ)
        return -EBUSY;
    struct completion *completion = &queue->completions[item->slot];
    if (completion->count)
        return -EALREADY;
    completion->status = lower_error;
    ++completion->count;
    ++queue->completions_count;
    if (item->kind == READ)
        ++queue->read_completed;
    if (lower_error && !queue->first_error)
        queue->first_error = lower_error;
    queue->owned_bytes -= item->bytes;
    queue->head = (queue->head + 1U) % QUEUE_SLOTS;
    --queue->count;
    queue->secondary_pressure_calls += 0U;
    queue->recompression_calls += 0U;
    return lower_error;
}

static int run_directed_tests(void)
{
    swapz_u32 reserve = 0;
    /* These two header functions are actual repository C, not a rewrite. */
    REQUIRE(swapz_authority_capacity_window(512U, 2048U, &reserve) == 1);
    REQUIRE(reserve == 512U);
    REQUIRE(swapz_authority_capacity_window(512U, 768U, NULL) == 0);
    struct swapz_pending_bio staged[1] = { { .logical = 9U, .length = 800U } };
    REQUIRE(swapz_window_read_independent(staged, 1U, 10U, 1U, 0) == 1);
    REQUIRE(swapz_window_read_independent(staged, 1U, 9U, 1U, 0) == 0);
    REQUIRE(SWAPZ_SOURCE_WORK_QUANTUM_BIOS == 64U);
    REQUIRE(SOURCE_MAPPED_AUTHENTICATED == 0);
    reset_model();
    struct external_event event = make_event(
        1U, ORIGINAL_COMPRESSED, 100U, SWAPZ_ZSWAP_IMPORT_LZ4_CODEC);
    event.natural = false;
    REQUIRE(admit(&model, &event) == -EPERM);
    event.natural = true;
    event.source_lease = false;
    REQUIRE(admit(&model, &event) == -EPERM);
    event.source_lease = true;
    event.observed_generation = 8U;
    REQUIRE(admit(&model, &event) == -ESTALE);
    event.observed_generation = 7U;
    event.codec = 99U;
    REQUIRE(admit(&model, &event) == -EOPNOTSUPP);
    event.codec = SWAPZ_ZSWAP_IMPORT_LZ4_CODEC;
    event.bytes = 0U;
    REQUIRE(admit(&model, &event) == -EMSGSIZE);
    event.bytes = SWAPZ_MAX_COMPRESSED + 1U;
    REQUIRE(admit(&model, &event) == -EMSGSIZE);
    event.bytes = 100U;
    REQUIRE(admit(&model, &event) == 0);
    REQUIRE(admit(&model, &event) == -EALREADY);
    const uint8_t last_copied_byte = event.payload[event.bytes - 1U];
    event.payload[event.bytes - 1U] ^= 0x5aU;
    REQUIRE(model.pending[model.head].payload[event.bytes - 1U] ==
            last_copied_byte);
    REQUIRE(model.pending[model.head].codec == SWAPZ_ZSWAP_IMPORT_LZ4_CODEC);
    REQUIRE(service_next(&model, 0) == 0);
    REQUIRE(admit(&model, &event) == -EALREADY);
    event = make_event(2U, ORIGINAL_RAW_4096, 100U, 0U);
    REQUIRE(admit(&model, &event) == -EINVAL);
    event.bytes = SWAPZ_BLOCK_BYTES;
    REQUIRE(admit(&model, &event) == 0);
    REQUIRE(model.pending[model.head].bytes == SWAPZ_BLOCK_BYTES);
    REQUIRE(service_next(&model, 0) == 0);

    /* Slot ceiling independently of the tighter byte ceiling. */
    reset_model();
    for (uint32_t slot = 0; slot < QUEUE_SLOTS; ++slot) {
        event = make_event(slot, ORIGINAL_COMPRESSED, 100U,
                           SWAPZ_ZSWAP_IMPORT_LZO1X_CODEC);
        REQUIRE(admit(&model, &event) == 0);
    }
    event = make_event(QUEUE_SLOTS, ORIGINAL_COMPRESSED, 100U,
                       SWAPZ_ZSWAP_IMPORT_LZ4_CODEC);
    REQUIRE(admit(&model, &event) == -EAGAIN);
    REQUIRE(model.peak_slots == QUEUE_SLOTS);
    REQUIRE(model.peak_bytes <= PENDING_LIMIT);

    /* Byte ceiling independently of the slot ceiling. */
    reset_model();
    for (uint32_t slot = 0; slot < PENDING_LIMIT / SWAPZ_BLOCK_BYTES; ++slot) {
        event = make_event(slot, FOREGROUND_WRITE, SWAPZ_BLOCK_BYTES, 0U);
        REQUIRE(admit(&model, &event) == 0);
    }
    event = make_event(30U, FOREGROUND_WRITE, SWAPZ_BLOCK_BYTES, 0U);
    REQUIRE(admit(&model, &event) == -EAGAIN);
    REQUIRE(model.peak_bytes == PENDING_LIMIT);

    /* Mixed finite accepted wave while lower writes are initially busy. */
    reset_model();
    for (uint32_t index = 0; index < 12U; ++index) {
        const uint32_t selector = index % 6U;
        const enum item_kind kind = selector == 0U || selector == 1U ?
            ORIGINAL_COMPRESSED : selector == 2U ?
            FOREGROUND_WRITE : selector == 3U || selector == 5U ?
            READ : ORIGINAL_RAW_4096;
        const uint32_t bytes = kind == READ ? 0U :
            kind == ORIGINAL_COMPRESSED ? (selector ? 1200U : 512U) :
            SWAPZ_BLOCK_BYTES;
        const uint8_t codec = kind != ORIGINAL_COMPRESSED ? 0U :
            selector ? SWAPZ_ZSWAP_IMPORT_LZO1X_CODEC :
                       SWAPZ_ZSWAP_IMPORT_LZ4_CODEC;
        event = make_event(50U + index, kind, bytes, codec);
        REQUIRE(admit(&model, &event) == 0);
    }
    REQUIRE(model.peak_slots == 12U);
    REQUIRE(model.owned_bytes <= PENDING_LIMIT);
    model.lower_busy = true;
    REQUIRE(service_next(&model, 0) == -EBUSY);
    REQUIRE(model.completions_count == 0U);
    model.lower_busy = false;
    uint32_t previous_completed = 0;
    for (uint32_t index = 0; index < 12U; ++index) {
        const uint32_t ticket = 50U + index;
        REQUIRE(model.pending[model.head].slot == ticket);
        const int lower_error = index == 9U ? -EIO : 0;
        REQUIRE(service_next(&model, lower_error) == lower_error);
        REQUIRE(model.completions[ticket].count == 1U);
        REQUIRE(model.completions[ticket].status == lower_error);
        REQUIRE(model.completions_count > previous_completed);
        previous_completed = model.completions_count;
    }
    REQUIRE(model.read_completed == 4U);
    REQUIRE(model.first_error == -EIO);
    REQUIRE(model.count == 0U && model.owned_bytes == 0U);
    REQUIRE(model.secondary_pressure_calls == 0U);
    REQUIRE(model.recompression_calls == 0U);
    model.closed = true;
    event = make_event(200U, ORIGINAL_COMPRESSED, 300U,
                       SWAPZ_ZSWAP_IMPORT_LZ4_CODEC);
    REQUIRE(admit(&model, &event) == -ESHUTDOWN);
    return 0;
}

int main(void)
{
    const int status = run_directed_tests();
    if (status)
        return status;
    printf("PASS round073-agent11 checks=%u quantum=%u peak_slots=%u "
           "pending_limit=%u read_completed=%u mm_external_only=1 "
           "secondary_pressure=0 recompression=0 "
           "RAW_4096=UNCOMPRESSED AUTH=0 PHASE_A=BLOCKED "
           "original_linux_native=NOT_RUN model_only=1\n",
           directed_checks, SWAPZ_SOURCE_WORK_QUANTUM_BIOS,
           model.peak_slots, PENDING_LIMIT, model.read_completed);
    return 0;
}
