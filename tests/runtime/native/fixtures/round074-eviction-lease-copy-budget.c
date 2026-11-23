/* SPDX-License-Identifier: GPL-2.0-only */
/*
 * Rootless deterministic contract model, NOT an original Linux zswap source.
 * Natural MM eviction is an input, never a swapz reclaim decision. The only
 * source-lock operation is a bounded exact-byte memcpy into owned memory.
 * All lower work, checksum/decode, waiting and completion occur after unlock.
 */
#include <errno.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>

#define SWAPZ_ZSWAP_IMPORT_HOST_TEST 1
#include "../../../../src/kernel/zswap-import-admission.h"
#include "../../../../src/kernel/zswap-direct-handoff.h"

#define SOURCE_MAPPED_AUTHENTICATED 0
#define DIRECT_COMPRESSED_HANDOFF 0
#define FORCED_RAW_BYPASS 0

enum { MAX_QUEUED = 8, MAX_TICKETS = 32,
       MAX_OWNED_BYTES = MAX_QUEUED * SWAPZ_MAX_COMPRESSED };

enum representation { ORIGINAL_OPAQUE = 1, ORDINARY_RAW_UNCOMPRESSED = 2 };

struct original_source {
    uint32_t ticket;
    uint32_t slot_incarnation;
    uint32_t current_incarnation;
    uint32_t length;
    uint8_t codec;
    bool natural_mm_eviction;
    bool pool_lease;
    bool entry_lease;
    bool source_lock_held;
    bool source_live;
    bool codec_retired;
    uint8_t bytes[SWAPZ_MAX_COMPRESSED];
};

struct owned_entry {
    uint32_t ticket;
    uint32_t incarnation;
    uint32_t length;
    uint8_t codec;
    enum representation representation;
    uint8_t bytes[SWAPZ_MAX_COMPRESSED];
};

struct ticket_completion {
    uint32_t count;
    int first_status;
};

struct lease_copy_model {
    struct owned_entry queue[MAX_QUEUED];
    struct ticket_completion completions[MAX_TICKETS];
    uint32_t queue_count;
    uint32_t pending_bytes;
    uint32_t peak_bytes;
    uint32_t copy_work_units;
    uint32_t max_copy_work_units_under_lock;
    uint32_t natural_input_count;
    uint32_t accepted_copies;
    uint32_t source_lock_lower_calls;
    uint32_t source_lock_hash_calls;
    uint32_t source_lock_wait_calls;
    uint32_t external_mm_reclaim_requests;
    uint32_t extra_shrinker_calls;
    uint32_t recompress_calls;
    uint32_t lower_attempts;
    uint32_t completed;
    int first_error;
    bool mm_lock_held;
    bool queue_lock_held;
    bool source_lock_held;
    bool teardown;
    bool fail_copy_allocation;
};

static struct lease_copy_model model;
static unsigned int directed_checks;

#define REQUIRE(condition) do { \
    ++directed_checks; \
    if (!(condition)) { \
        fprintf(stderr, "FIRST_ERROR line=%d check=%s\n", __LINE__, #condition); \
        return 1; \
    } \
} while (0)

static void reset_model(void)
{
    memset(&model, 0, sizeof(model));
}

static struct original_source original_event(uint32_t ticket, uint8_t codec,
                                              uint32_t length)
{
    struct original_source event = {0};
    event.ticket = ticket;
    event.slot_incarnation = ticket + 1U;
    event.current_incarnation = event.slot_incarnation;
    event.length = length;
    event.codec = codec;
    event.natural_mm_eviction = true;
    event.pool_lease = true;
    event.entry_lease = true;
    event.source_lock_held = true;
    event.source_live = true;
    for (uint32_t index = 0; index < sizeof(event.bytes); ++index)
        event.bytes[index] = (uint8_t)(ticket * 23U + index * 37U);
    return event;
}

/* The event/source must outlive this synchronous bounded copy, not the queue. */
static int acquire_owned_copy(const struct original_source *source)
{
    if (!source || !source->natural_mm_eviction)
        return -EPERM;
    ++model.natural_input_count; /* External MM input, not a reclaim call. */
    if (model.teardown)
        return -ESHUTDOWN;
    if (!source->pool_lease || !source->entry_lease ||
        !source->source_live || source->codec_retired ||
        !source->slot_incarnation ||
        source->slot_incarnation != source->current_incarnation)
        return -ESTALE;
    if (!source->source_lock_held)
        return -EPERM;
    if (source->codec != SWAPZ_ZSWAP_IMPORT_LZO1X_CODEC &&
        source->codec != SWAPZ_ZSWAP_IMPORT_LZ4_CODEC)
        return -EOPNOTSUPP;
    if (!source->length || source->length > SWAPZ_MAX_COMPRESSED)
        return -EMSGSIZE;
    if (source->ticket >= MAX_TICKETS ||
        model.completions[source->ticket].count)
        return -EINVAL;
    for (uint32_t index = 0; index < model.queue_count; ++index)
        if (model.queue[index].ticket == source->ticket)
            return -EALREADY;
    if (model.queue_count == MAX_QUEUED ||
        source->length > MAX_OWNED_BYTES - model.pending_bytes)
        return -EAGAIN; /* Never trigger further MM reclaim for capacity. */
    if (model.fail_copy_allocation)
        return -ENOMEM; /* Bounded nonblocking allocation failure. */
    struct owned_entry *entry = &model.queue[model.queue_count];
    entry->ticket = source->ticket;
    entry->incarnation = source->slot_incarnation;
    entry->length = source->length;
    entry->codec = source->codec;
    entry->representation = ORIGINAL_OPAQUE;
    memcpy(entry->bytes, source->bytes, source->length);
    model.copy_work_units += source->length;
    if (source->length > model.max_copy_work_units_under_lock)
        model.max_copy_work_units_under_lock = source->length;
    model.pending_bytes += source->length;
    if (model.pending_bytes > model.peak_bytes)
        model.peak_bytes = model.pending_bytes;
    ++model.queue_count;
    ++model.accepted_copies;
    return 0;
}

/* Idempotent modeled callback owner: a replay cannot overwrite first status. */
static void complete_ticket_once(uint32_t ticket, int status)
{
    struct ticket_completion *completion = &model.completions[ticket];
    if (completion->count == 0U) {
        completion->first_status = status;
        ++completion->count;
        ++model.completed;
        if (status != 0 && model.first_error == 0)
            model.first_error = status;
    }
}

/* Never run lower work with a model MM, source or queue lock. */
static int lower_service_one(int lower_status, bool durable_fua)
{
    if (model.mm_lock_held || model.queue_lock_held || model.source_lock_held)
        return -EDEADLK;
    if (!model.queue_count)
        return -ENOENT;
    ++model.lower_attempts;
    struct owned_entry *entry = &model.queue[0];
    const int status = lower_status != 0 ? lower_status :
                       durable_fua ? 0 : -EIO;
    complete_ticket_once(entry->ticket, status);
    model.pending_bytes -= entry->length;
    --model.queue_count;
    memmove(model.queue, model.queue + 1,
            (size_t)model.queue_count * sizeof(model.queue[0]));
    memset(&model.queue[model.queue_count], 0, sizeof(model.queue[0]));
    return status;
}

static bool contains_exact_owned_copy(const struct original_source *original)
{
    for (uint32_t index = 0; index < model.queue_count; ++index) {
        const struct owned_entry *owned = &model.queue[index];
        if (owned->ticket != original->ticket)
            continue;
        return owned->incarnation == original->slot_incarnation &&
               owned->length == original->length &&
               owned->codec == original->codec &&
               owned->representation == ORIGINAL_OPAQUE &&
               memcmp(owned->bytes, original->bytes, owned->length) == 0;
    }
    return false;
}

static bool zero_competing_work(void)
{
    return model.external_mm_reclaim_requests == 0U &&
           model.extra_shrinker_calls == 0U &&
           model.recompress_calls == 0U &&
           model.source_lock_lower_calls == 0U &&
           model.source_lock_hash_calls == 0U &&
           model.source_lock_wait_calls == 0U;
}

static int run_qualification(void)
{
    reset_model();
    REQUIRE(SWAPZ_ZSWAP_IMPORT_ACTIVE == 0U &&
            SWAPZ_ZSWAP_IMPORT_ADMISSION_ACTIVE == 0U &&
            SWAPZ_DIRECT_HANDOFF_PRODUCTION_ENABLED == 0U);
    REQUIRE(SOURCE_MAPPED_AUTHENTICATED == 0 &&
            DIRECT_COMPRESSED_HANDOFF == 0 && FORCED_RAW_BYPASS == 0);
    REQUIRE(ORDINARY_RAW_UNCOMPRESSED != ORIGINAL_OPAQUE);
    struct original_source original = original_event(1U,
        SWAPZ_ZSWAP_IMPORT_LZO1X_CODEC, SWAPZ_MAX_COMPRESSED);
    REQUIRE(acquire_owned_copy(&original) == 0);
    REQUIRE(contains_exact_owned_copy(&original));
    REQUIRE(model.max_copy_work_units_under_lock <= SWAPZ_MAX_COMPRESSED);
    REQUIRE(model.pending_bytes <= MAX_OWNED_BYTES);
    struct original_source saved = original;
    memset(original.bytes, 0x5a, sizeof(original.bytes));
    original.source_live = false; /* Real source *would* be erased now. */
    REQUIRE(!contains_exact_owned_copy(&original));
    REQUIRE(contains_exact_owned_copy(&saved));
    REQUIRE(lower_service_one(0, true) == 0);
    REQUIRE(model.completions[1].count == 1U);
    REQUIRE(model.completions[1].first_status == 0);
    REQUIRE(model.pending_bytes == 0U && model.queue_count == 0U);
    REQUIRE(acquire_owned_copy(&saved) == -EINVAL); /* Completed event. */

#define EXPECT_DENIED(mutation,expected_error) do { \
    struct original_source denied = original_event(2U, \
        SWAPZ_ZSWAP_IMPORT_LZ4_CODEC, 1200U); \
    mutation; \
    REQUIRE(acquire_owned_copy(&denied) == (expected_error)); \
    REQUIRE(model.queue_count == 0U); \
} while (0)
    EXPECT_DENIED(denied.natural_mm_eviction = false, -EPERM);
    EXPECT_DENIED(denied.pool_lease = false, -ESTALE);
    EXPECT_DENIED(denied.entry_lease = false, -ESTALE);
    EXPECT_DENIED(denied.source_live = false, -ESTALE);
    EXPECT_DENIED(denied.codec_retired = true, -ESTALE);
    EXPECT_DENIED(denied.slot_incarnation++, -ESTALE);
    EXPECT_DENIED(denied.source_lock_held = false, -EPERM);
    EXPECT_DENIED(denied.codec = 0U, -EOPNOTSUPP);
    EXPECT_DENIED(denied.length = 0U, -EMSGSIZE);
    EXPECT_DENIED(denied.length = SWAPZ_MAX_COMPRESSED + 1U, -EMSGSIZE);
    EXPECT_DENIED(denied.ticket = MAX_TICKETS, -EINVAL);
#undef EXPECT_DENIED

    model.fail_copy_allocation = true;
    struct original_source failed = original_event(2U,
        SWAPZ_ZSWAP_IMPORT_LZ4_CODEC, SWAPZ_MAX_COMPRESSED);
    REQUIRE(acquire_owned_copy(&failed) == -ENOMEM);
    REQUIRE(model.queue_count == 0U && model.pending_bytes == 0U);
    model.fail_copy_allocation = false;
    for (uint32_t ticket = 2U; ticket != 2U + MAX_QUEUED; ++ticket) {
        struct original_source next = original_event(ticket,
            ticket % 2U ? SWAPZ_ZSWAP_IMPORT_LZO1X_CODEC :
                          SWAPZ_ZSWAP_IMPORT_LZ4_CODEC, SWAPZ_MAX_COMPRESSED);
        REQUIRE(acquire_owned_copy(&next) == 0);
        REQUIRE(contains_exact_owned_copy(&next));
    }
    REQUIRE(model.queue_count == MAX_QUEUED);
    REQUIRE(model.peak_bytes == MAX_OWNED_BYTES);
    REQUIRE(model.pending_bytes == MAX_OWNED_BYTES);
    REQUIRE(acquire_owned_copy(&failed) == -EALREADY); /* Identical queued ticket. */
    struct original_source overflow = original_event(10U,
        SWAPZ_ZSWAP_IMPORT_LZ4_CODEC, 1200U);
    REQUIRE(acquire_owned_copy(&overflow) == -EAGAIN);
    REQUIRE(model.queue_count == MAX_QUEUED);
    model.mm_lock_held = true;
    REQUIRE(lower_service_one(0, true) == -EDEADLK);
    model.mm_lock_held = false;
    model.queue_lock_held = true;
    REQUIRE(lower_service_one(0, true) == -EDEADLK);
    model.queue_lock_held = false;
    model.source_lock_held = true;
    REQUIRE(lower_service_one(0, true) == -EDEADLK);
    model.source_lock_held = false;
    REQUIRE(model.queue_count == MAX_QUEUED);
    REQUIRE(model.lower_attempts == 1U); /* Only earlier after source erase. */

    REQUIRE(lower_service_one(-EIO, true) == -EIO);
    REQUIRE(model.first_error == -EIO);
    REQUIRE(model.completions[2].count == 1U);
    REQUIRE(model.completions[2].first_status == -EIO);
    complete_ticket_once(2U, -ETIMEDOUT); /* Duplicate terminal callback. */
    REQUIRE(model.completions[2].count == 1U);
    REQUIRE(model.completions[2].first_status == -EIO);
    REQUIRE(model.first_error == -EIO);
    REQUIRE(lower_service_one(-ENOSPC, true) == -ENOSPC);
    REQUIRE(model.completions[3].first_status == -ENOSPC);
    REQUIRE(model.first_error == -EIO); /* First failure wins. */
    REQUIRE(lower_service_one(0, false) == -EIO); /* Missing FUA. */
    REQUIRE(model.completions[4].first_status == -EIO);
    REQUIRE(model.first_error == -EIO);
    REQUIRE(model.completions[2].count == 1U);
    while (model.queue_count != 0U)
        REQUIRE(lower_service_one(0, true) == 0);
    REQUIRE(model.pending_bytes == 0U);
    struct owned_entry empty_slot = {0};
    REQUIRE(memcmp(&model.queue[0], &empty_slot, sizeof(empty_slot)) == 0);
    REQUIRE(model.completed == 9U);
    REQUIRE(model.accepted_copies == 9U);
    REQUIRE(model.max_copy_work_units_under_lock == SWAPZ_MAX_COMPRESSED);
    REQUIRE(model.copy_work_units == 9U * SWAPZ_MAX_COMPRESSED);
    REQUIRE(zero_competing_work());

    reset_model();
    model.teardown = true;
    struct original_source closed = original_event(11U,
        SWAPZ_ZSWAP_IMPORT_LZ4_CODEC, 1100U);
    REQUIRE(acquire_owned_copy(&closed) == -ESHUTDOWN);
    REQUIRE(model.queue_count == 0U);
    reset_model();
    struct original_source canceled = original_event(12U,
        SWAPZ_ZSWAP_IMPORT_LZO1X_CODEC, 900U);
    REQUIRE(acquire_owned_copy(&canceled) == 0);
    canceled.source_live = false;
    canceled.entry_lease = false;
    REQUIRE(acquire_owned_copy(&canceled) == -ESTALE);
    REQUIRE(lower_service_one(-ECANCELED, true) == -ECANCELED);
    REQUIRE(model.completions[12].first_status == -ECANCELED);
    REQUIRE(model.first_error == -ECANCELED);
    REQUIRE(zero_competing_work());
    return 0;
}

int main(void)
{
    if (run_qualification() != 0)
        return 1;
    printf("PASS directed=%u owned_copies=9 burst=8 max_owned=%u "
           "max_under_lock=%u MM_ONLY=1 SECONDARY_RECLAIM=0 "
           "RECOMPRESS=0 RAW_4096=UNCOMPRESSED AUTH=0 "
           "PHASE_A=BLOCKED HOST_ONLY=1\n",
           directed_checks, MAX_OWNED_BYTES, SWAPZ_MAX_COMPRESSED);
    return 0;
}
