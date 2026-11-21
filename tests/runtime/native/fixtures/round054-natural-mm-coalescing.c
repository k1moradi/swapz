/* SPDX-License-Identifier: GPL-2.0-only */
/* Rootless synthetic disk scheduler, not an MM producer, codec or DM target. */
#include <errno.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include "../../../../src/kernel/codec.h"

enum { BLOCKS = 64, QUEUE = 8, PACK = 4, WAIT = 2, RESERVE = 4,
       SLOTS = 64, EVENTS = 128 };
#define SOURCE_MAPPED_AUTHENTICATED 0
#define DIRECT_COMPRESSED_HANDOFF 0
#define FORCED_RAW_BYPASS 0
#define CHECK(name, condition) do { if (!(condition)) { \
    fprintf(stderr, "FIRST_ERROR %s\n", name); return 1; } } while (0)

struct event {
    unsigned int id, slot, generation, observed, epoch, arrival, bytes, length;
    bool native, cancel, eio;
    uint8_t page[SWAPZ_BLOCK_BYTES];
};
struct map {
    unsigned int start, blocks, offset, length, generation, id;
    bool live;
};
struct ticket {
    unsigned int token, start, blocks, count, payload, epoch;
    bool active;
};
struct costs {
    unsigned int decode, compress, upper, requests, written, payload, padding;
    unsigned int gc_requests, gc_bytes, max_queue, max_wait, success, failed, refused;
    unsigned int attempted_bytes;
    uint64_t successful_ids[EVENTS / 64];
};
struct model {
    uint8_t disk[BLOCKS * SWAPZ_BLOCK_BYTES], header[SWAPZ_BLOCK_BYTES], partition[64];
    bool used[BLOCKS], accepted[EVENTS];
    unsigned int ack[EVENTS];
    struct event pending[QUEUE];
    struct map maps[SLOTS];
    struct ticket active;
    struct costs cost;
    unsigned int capacity, reserve, reserve_blocks, count, tick, epoch, next_token, last_ack;
    bool coalesce, closed;
};
static struct model disk;

static uint8_t original_byte(unsigned int id, unsigned int offset)
{
    return (uint8_t)(id * 43U + offset * 17U + (offset >> 8U));
}
static struct event event_at(unsigned int id, unsigned int slot, unsigned int length)
{
    struct event event = { .id = id, .slot = slot, .generation = id + 1U,
        .observed = id + 1U, .epoch = disk.epoch, .arrival = disk.tick,
        .bytes = SWAPZ_BLOCK_BYTES, .length = length, .native = true };
    for (unsigned int i = 0; i < SWAPZ_BLOCK_BYTES; ++i)
        event.page[i] = original_byte(id, i);
    return event;
}
static bool full_page(const struct event *event)
{
    if (event->bytes != SWAPZ_BLOCK_BYTES)
        return false;
    for (unsigned int i = 0; i < SWAPZ_BLOCK_BYTES; ++i)
        if (event->page[i] != original_byte(event->id, i))
            return false;
    return true;
}
static void reset(unsigned int capacity, bool coalesce)
{
    memset(&disk, 0, sizeof(disk));
    disk.capacity = capacity;
    disk.reserve_blocks = RESERVE;
    disk.reserve = capacity - disk.reserve_blocks;
    disk.coalesce = coalesce;
    disk.epoch = 1U;
    disk.used[0] = true;
    for (unsigned int i = 0; i < SWAPZ_BLOCK_BYTES; ++i)
        disk.header[i] = original_byte(0U, i);
    memcpy(disk.disk, disk.header, sizeof(disk.header));
    memset(disk.partition, 0xa5, sizeof(disk.partition));
}
static bool reserved(unsigned int block)
{
    return block >= disk.reserve && block < disk.reserve + disk.reserve_blocks;
}
static bool intact(void)
{
    if (!disk.used[0] || memcmp(disk.header, disk.disk, sizeof(disk.header)))
        return false;
    for (unsigned int i = 0; i < sizeof(disk.partition); ++i)
        if (disk.partition[i] != 0xa5U)
            return false;
    for (unsigned int i = disk.reserve; i < disk.reserve + disk.reserve_blocks; ++i)
        if (disk.used[i])
            return false;
    for (unsigned int i = 0; i < SLOTS; ++i) {
        const struct map *left = &disk.maps[i];
        if (!left->live)
            continue;
        if (!left->start || left->start + left->blocks > disk.capacity ||
            left->offset + left->length > left->blocks * SWAPZ_BLOCK_BYTES)
            return false;
        for (unsigned int k = 0; k < left->blocks; ++k)
            if (!disk.used[left->start + k] || reserved(left->start + k))
                return false;
        for (unsigned int j = i + 1U; j < SLOTS; ++j) {
            const struct map *right = &disk.maps[j];
            if (!right->live)
                continue;
            if (left->start == right->start) {
                if (left->blocks != right->blocks ||
                    (left->offset < right->offset + right->length &&
                     right->offset < left->offset + left->length))
                    return false;
            } else if (left->start < right->start + right->blocks &&
                       right->start < left->start + left->blocks)
                return false;
        }
    }
    return true;
}
static int admit(const struct event *event)
{
    if (disk.closed || !event->native || event->id >= EVENTS || event->slot >= SLOTS ||
        event->id <= disk.last_ack || disk.accepted[event->id] || !full_page(event) ||
        (disk.count && event->id <= disk.pending[disk.count - 1U].id))
        return -EINVAL;
    if (disk.count >= QUEUE) {
        ++disk.cost.refused;
        return -EAGAIN;
    }
    disk.pending[disk.count++] = *event;
    disk.accepted[event->id] = true;
    ++disk.cost.decode;
    ++disk.cost.compress;
    disk.cost.upper += SWAPZ_BLOCK_BYTES;
    if (disk.count > disk.cost.max_queue)
        disk.cost.max_queue = disk.count;
    return 0;
}
static unsigned int payload_length(const struct event *event)
{
    return event->length && event->length <= SWAPZ_MAX_COMPRESSED ?
        event->length : SWAPZ_BLOCK_BYTES;
}
static bool current(const struct event *event)
{
    return !disk.closed && !event->cancel && event->epoch == disk.epoch &&
           event->generation == event->observed && full_page(event);
}
static void mark(unsigned int start, unsigned int blocks, bool value)
{
    for (unsigned int i = 0; i < blocks; ++i)
        disk.used[start + i] = value;
}
static unsigned int allocate(unsigned int blocks)
{
    for (unsigned int start = 1; start + blocks <= disk.capacity; ++start) {
        unsigned int i = 0;
        while (i < blocks && !disk.used[start + i] && !reserved(start + i))
            ++i;
        if (i == blocks) {
            mark(start, blocks, true);
            return start;
        }
    }
    return 0;
}
static void release_if_unused(struct map old)
{
    if (!old.live)
        return;
    for (unsigned int i = 0; i < SLOTS; ++i)
        if (disk.maps[i].live && disk.maps[i].start == old.start)
            return;
    mark(old.start, old.blocks, false);
}
static bool finish(unsigned int count, bool success)
{
    for (unsigned int i = 0; i < count; ++i) {
        const struct event *event = &disk.pending[i];
        if (!disk.accepted[event->id] || disk.ack[event->id] || event->id <= disk.last_ack)
            return false;
        ++disk.ack[event->id];
        disk.last_ack = event->id;
        unsigned int wait = disk.tick - event->arrival;
        if (wait > disk.cost.max_wait)
            disk.cost.max_wait = wait;
        if (success) {
            ++disk.cost.success;
            disk.cost.successful_ids[event->id / 64U] |= UINT64_C(1) << (event->id % 64U);
        } else
            ++disk.cost.failed;
    }
    disk.count -= count;
    memmove(disk.pending, disk.pending + count, disk.count * sizeof(disk.pending[0]));
    return true;
}
static unsigned int plan_count(void)
{
    const struct event *first = &disk.pending[0];
    if (!disk.coalesce || payload_length(first) == SWAPZ_BLOCK_BYTES || first->eio)
        return 1U;
    unsigned int count = 1U;
    while (count < disk.count && count < PACK) {
        const struct event *next = &disk.pending[count];
        if (!current(next) || next->eio || payload_length(next) == SWAPZ_BLOCK_BYTES)
            break;
        bool duplicate = false;
        for (unsigned int i = 0; i < count; ++i)
            if (disk.pending[i].slot == next->slot)
                duplicate = true;
        if (duplicate)
            break;
        ++count;
    }
    return count;
}
/* Staging reserves COW space; neither a submission nor a late callback is ACK. */
static int stage(void)
{
    if (!disk.count || disk.active.active)
        return -EAGAIN;
    if (!current(&disk.pending[0]))
        return finish(1U, false) ? -ECANCELED : -EINVAL;
    unsigned int count = plan_count();
    unsigned int payload = 0;
    for (unsigned int i = 0; i < count; ++i)
        payload += payload_length(&disk.pending[i]);
    unsigned int blocks = payload <= SWAPZ_BLOCK_BYTES ? 1U :
        payload <= 2U * SWAPZ_BLOCK_BYTES ? 2U : 4U;
    /* Do not spend four blocks for three records when two smaller packs fit. */
    while (blocks > count) {
        payload -= payload_length(&disk.pending[--count]);
        blocks = payload <= SWAPZ_BLOCK_BYTES ? 1U :
            payload <= 2U * SWAPZ_BLOCK_BYTES ? 2U : 4U;
    }
    unsigned int start = allocate(blocks);
    /* If a large pack cannot fit contiguous space, try one page once. */
    if (!start && count > 1U) {
        count = 1U;
        payload = payload_length(&disk.pending[0]);
        blocks = 1U;
        start = allocate(blocks);
    }
    if (!start)
        return finish(1U, false) ? -ENOSPC : -EINVAL;
    disk.active = (struct ticket){ .token = ++disk.next_token, .start = start,
        .blocks = blocks, .count = count, .payload = payload, .epoch = disk.epoch,
        .active = true };
    uint8_t *destination = disk.disk + start * SWAPZ_BLOCK_BYTES;
    memset(destination, 0, blocks * SWAPZ_BLOCK_BYTES);
    unsigned int cursor = 0;
    for (unsigned int i = 0; i < count; ++i) {
        unsigned int length = payload_length(&disk.pending[i]);
        memcpy(destination + cursor, disk.pending[i].page, length);
        cursor += length;
    }
    ++disk.cost.requests;
    disk.cost.attempted_bytes += blocks * SWAPZ_BLOCK_BYTES;
    return 0;
}
static int complete(unsigned int token, bool durable)
{
    struct ticket ticket = disk.active;
    if (!ticket.active || token != ticket.token)
        return -ESTALE;
    disk.active.active = false;
    bool valid = durable && ticket.epoch == disk.epoch;
    for (unsigned int i = 0; i < ticket.count; ++i)
        valid = valid && current(&disk.pending[i]) && !disk.pending[i].eio;
    if (!valid) {
        mark(ticket.start, ticket.blocks, false);
        return finish(ticket.count, false) ? -EIO : -EINVAL;
    }
    unsigned int cursor = 0;
    for (unsigned int i = 0; i < ticket.count; ++i) {
        const struct event *event = &disk.pending[i];
        struct map old = disk.maps[event->slot];
        unsigned int length = payload_length(event);
        disk.maps[event->slot] = (struct map){ .start = ticket.start,
            .blocks = ticket.blocks, .offset = cursor, .length = length,
            .generation = event->generation, .id = event->id, .live = true };
        cursor += length;
        release_if_unused(old);
    }
    disk.cost.written += ticket.blocks * SWAPZ_BLOCK_BYTES;
    disk.cost.payload += ticket.payload;
    disk.cost.padding += ticket.blocks * SWAPZ_BLOCK_BYTES - ticket.payload;
    return finish(ticket.count, true) ? 0 : -EINVAL;
}
static bool map_matches(unsigned int slot, unsigned int id, unsigned int length)
{
    const struct map *map = &disk.maps[slot];
    if (!map->live || map->id != id || map->generation != id + 1U || map->length != length)
        return false;
    const uint8_t *data = disk.disk + map->start * SWAPZ_BLOCK_BYTES + map->offset;
    /* Short records are opaque synthetic prefixes, not real LZ4. */
    for (unsigned int i = 0; i < length; ++i)
        if (data[i] != original_byte(id, i))
            return false;
    return true;
}
/* One explicit GC COW move of a four-block extent rotates the reserve.
 * The comparative frontier may select a smaller equal-class reserve. */
static int relocate(unsigned int slot, bool durable)
{
    struct map old = disk.maps[slot];
    if (!old.live || old.blocks != disk.reserve_blocks || disk.active.active)
        return -EINVAL;
    unsigned int destination = disk.reserve;
    memcpy(disk.disk + destination * SWAPZ_BLOCK_BYTES,
           disk.disk + old.start * SWAPZ_BLOCK_BYTES, disk.reserve_blocks * SWAPZ_BLOCK_BYTES);
    ++disk.cost.gc_requests;
    if (!durable)
        return -EIO;
    mark(destination, disk.reserve_blocks, true);
    for (unsigned int i = 0; i < SLOTS; ++i)
        if (disk.maps[i].live && disk.maps[i].start == old.start)
            disk.maps[i].start = destination;
    mark(old.start, disk.reserve_blocks, false);
    disk.reserve = old.start;
    ++disk.epoch;
    disk.cost.gc_bytes += disk.reserve_blocks * SWAPZ_BLOCK_BYTES;
    return 0;
}
static bool ready(void)
{
    return disk.count && (!disk.coalesce || disk.count >= PACK ||
        disk.pending[0].cancel || disk.closed ||
        disk.tick - disk.pending[0].arrival >= WAIT);
}
/* Instantaneous lower completion is a model step, not a physical latency bound.
 * At most QUEUE accepted events can retire at a tick; never manufacture arrivals. */
static int service(void)
{
    for (unsigned int attempt = 0; attempt < QUEUE && ready(); ++attempt) {
        int error = stage();
        if (error == 0)
            error = complete(disk.active.token, true);
        if (error != 0 && error != -EIO && error != -ENOSPC && error != -ECANCELED)
            return error;
    }
    return 0;
}
static bool padding_zero(void)
{
    for (unsigned int i = 0; i < SLOTS; ++i) {
        struct map map = disk.maps[i];
        if (!map.live)
            continue;
        unsigned int end = 0;
        for (unsigned int j = 0; j < SLOTS; ++j)
            if (disk.maps[j].live && disk.maps[j].start == map.start &&
                disk.maps[j].offset + disk.maps[j].length > end)
                end = disk.maps[j].offset + disk.maps[j].length;
        for (unsigned int j = end; j < map.blocks * SWAPZ_BLOCK_BYTES; ++j)
            if (disk.disk[map.start * SWAPZ_BLOCK_BYTES + j])
                return false;
    }
    return true;
}
/* Independent, identical trace generator for both policies. No source callback. */
static int trace(unsigned int variant, bool coalesce, struct costs *out)
{
    const unsigned int lengths[] = { 700U, 1900U, 3000U, 3568U, 3569U, 0U };
    reset(16U << (variant % 3U), coalesce);
    unsigned int id = 1U;
    for (disk.tick = 0; disk.tick < 12U; ++disk.tick) {
        unsigned int arrivals = variant % 4U == 0U ? 4U :
            variant % 4U == 1U ? (disk.tick % 3U == 0U ? 3U : 0U) :
            variant % 4U == 2U ? 1U : (disk.tick % 2U ? 0U : 2U);
        if (disk.tick >= 6U)
            arrivals = 0U;
        for (unsigned int i = 0; i < arrivals; ++i) {
            unsigned int length = lengths[(variant / 4U + i) % 6U];
            struct event event = event_at(id, id, length);
            if (variant >= 36U && id % 5U == 0U)
                event.eio = true;
            CHECK("trace_admit", admit(&event) == 0);
            ++id;
        }
        CHECK("trace_service", service() == 0);
        CHECK("reserve_and_header", intact());
    }
    CHECK("trace_drained", disk.count == 0U && !disk.active.active);
    CHECK("fair_wait", disk.cost.max_wait <= WAIT);
    CHECK("cost_identity", disk.cost.decode == id - 1U && disk.cost.compress == id - 1U &&
          disk.cost.upper == (id - 1U) * SWAPZ_BLOCK_BYTES &&
          disk.cost.written == disk.cost.payload + disk.cost.padding);
    for (unsigned int i = 1; i < id; ++i) {
        CHECK("exactly_once", disk.ack[i] == 1U);
        if (disk.maps[i].live)
            CHECK("readback", map_matches(i, i, disk.maps[i].length));
    }
    CHECK("padding", padding_zero());
    *out = disk.cost;
    return 0;
}
static int queue_case(void)
{
    reset(64U, true);
    for (unsigned int i = 1; i <= QUEUE; ++i) {
        struct event event = event_at(i, i, 700U);
        CHECK("queue_capacity", admit(&event) == 0);
    }
    struct event extra = event_at(9U, 9U, 700U);
    CHECK("queue_backpressure", admit(&extra) == -EAGAIN && !disk.accepted[9] && !disk.ack[9]);
    CHECK("queue_drain", service() == 0 && disk.count == 0U && disk.cost.max_queue == QUEUE);
    return 0;
}
static int deadline_case(void)
{
    reset(16U, true);
    struct event event = event_at(1U, 1U, 700U);
    CHECK("deadline_admit", admit(&event) == 0 && service() == 0 && disk.count == 1U);
    ++disk.tick;
    CHECK("deadline_early", service() == 0 && disk.count == 1U);
    ++disk.tick;
    CHECK("deadline_retire", service() == 0 && disk.count == 0U && disk.ack[1] == 1U);
    return 0;
}
static int fifo_case(void)
{
    reset(16U, false);
    for (unsigned int i = 1; i <= PACK; ++i) {
        struct event event = event_at(i, i, 700U);
        CHECK("fifo_admit", admit(&event) == 0);
    }
    CHECK("fifo_single", service() == 0 && disk.cost.requests == PACK && disk.cost.max_wait == 0U);
    return 0;
}
static int reserve_case(void)
{
    reset(16U, false);
    for (unsigned int i = 1; i <= 12U; ++i) {
        struct event event = event_at(i, i, 0U);
        CHECK("reserve_admit", admit(&event) == 0 && service() == 0);
    }
    CHECK("reserve_capacity", intact() && disk.cost.success == 11U && disk.cost.failed == 1U);
    CHECK("reserve_old_read", map_matches(1U, 1U, SWAPZ_BLOCK_BYTES));
    return 0;
}
static int callback_case(void)
{
    reset(16U, false);
    struct event original = event_at(1U, 1U, 0U);
    CHECK("callback_initial", admit(&original) == 0 && service() == 0);
    struct event retry = event_at(2U, 1U, 0U);
    CHECK("callback_stage", admit(&retry) == 0 && stage() == 0);
    unsigned int token = disk.active.token;
    CHECK("callback_late", complete(token - 1U, true) == -ESTALE && !disk.ack[2]);
    CHECK("callback_before_durable", map_matches(1U, 1U, SWAPZ_BLOCK_BYTES));
    CHECK("callback_eio", complete(token, false) == -EIO && disk.ack[2] == 1U);
    CHECK("callback_rollback", map_matches(1U, 1U, SWAPZ_BLOCK_BYTES));
    CHECK("callback_duplicate", complete(token, true) == -ESTALE && disk.ack[2] == 1U);
    retry = event_at(3U, 1U, 3569U);
    CHECK("callback_retry", admit(&retry) == 0 && service() == 0 && map_matches(1U, 3U, SWAPZ_BLOCK_BYTES));
    return 0;
}
static int gc_case(void)
{
    reset(16U, true);
    for (unsigned int i = 1; i <= PACK; ++i) {
        struct event event = event_at(i, i, 3000U);
        CHECK("gc_admit", admit(&event) == 0);
    }
    CHECK("gc_pack", service() == 0 && disk.maps[1].blocks == 4U);
    unsigned int old = disk.maps[1].start;
    struct event stale = event_at(5U, 1U, 0U);
    CHECK("gc_pending", admit(&stale) == 0);
    CHECK("gc_error", relocate(1U, false) == -EIO && disk.maps[1].start == old);
    CHECK("gc_move", relocate(1U, true) == 0 && disk.maps[1].start != old && intact());
    CHECK("gc_cost", disk.cost.gc_requests == 2U && disk.cost.gc_bytes == 4U * SWAPZ_BLOCK_BYTES);
    disk.tick += WAIT;
    CHECK("gc_stale", service() == 0 && disk.cost.failed == 1U && map_matches(1U, 1U, 3000U));
    struct event aba = event_at(6U, 1U, 0U);
    ++aba.observed;
    CHECK("gc_aba_admit", admit(&aba) == 0);
    disk.tick += WAIT;
    CHECK("gc_aba", service() == 0 && disk.cost.failed == 2U && map_matches(1U, 1U, 3000U));
    for (unsigned int i = 1U; i <= PACK; ++i)
        CHECK("gc_readback", map_matches(i, i, 3000U));
    return 0;
}
static int input_case(void)
{
    reset(16U, false);
    struct event compressed = event_at(1U, 1U, 700U);
    compressed.bytes = 700U;
    CHECK("raw_size", admit(&compressed) == -EINVAL && !disk.accepted[1]);
    struct event event = event_at(2U, 1U, 0U);
    event.page[SWAPZ_BLOCK_BYTES - 1U] ^= 1U;
    CHECK("raw_content", admit(&event) == -EINVAL && !disk.accepted[2]);
    event = event_at(3U, 1U, 0U);
    event.native = false;
    CHECK("native_only", admit(&event) == -EINVAL && !disk.accepted[3]);
    return 0;
}
static int cancel_case(void)
{
    reset(16U, false);
    struct event first = event_at(1U, 1U, 0U);
    CHECK("cancel_initial", admit(&first) == 0 && service() == 0);
    struct event next = event_at(2U, 1U, 0U);
    CHECK("cancel_stage", admit(&next) == 0 && stage() == 0);
    disk.pending[0].cancel = true; /* synthetic swapoff */
    CHECK("cancel_swapoff", complete(disk.active.token, true) == -EIO && map_matches(1U, 1U, SWAPZ_BLOCK_BYTES));
    next = event_at(3U, 1U, 0U);
    CHECK("cancel_dtr_stage", admit(&next) == 0 && stage() == 0);
    disk.closed = true;
    CHECK("cancel_dtr", complete(disk.active.token, true) == -EIO && map_matches(1U, 1U, SWAPZ_BLOCK_BYTES));
    next = event_at(4U, 1U, 0U);
    CHECK("cancel_refuse", admit(&next) == -EINVAL && !disk.ack[4]);
    return 0;
}
static int padding_case(void)
{
    reset(16U, true);
    for (unsigned int i = 1; i <= 3U; ++i) {
        struct event event = event_at(i, i, 3000U);
        CHECK("padding_admit", admit(&event) == 0);
    }
    disk.tick += WAIT;
    CHECK("padding_no_amplification", service() == 0 && disk.cost.requests == 2U &&
          disk.cost.written == 3U * SWAPZ_BLOCK_BYTES && disk.cost.success == 3U);
    CHECK("padding_preserved", intact() && padding_zero());
    return 0;
}
static const struct { const char *name; int (*run)(void); } cases[] = {
    {"queue", queue_case}, {"deadline", deadline_case}, {"fifo", fifo_case},
    {"reserve", reserve_case}, {"callback", callback_case}, {"gc", gc_case},
    {"input", input_case}, {"cancel", cancel_case}, {"padding", padding_case},
};
int main(int argc, char **argv)
{
    if (argc == 2) {
        for (unsigned int i = 0; i < sizeof(cases) / sizeof(cases[0]); ++i)
            if (!strcmp(argv[1], cases[i].name))
                return cases[i].run();
        return 2;
    }
    CHECK("no_auth", SOURCE_MAPPED_AUTHENTICATED == 0 && DIRECT_COMPRESSED_HANDOFF == 0 && FORCED_RAW_BYPASS == 0);
    for (unsigned int i = 0; i < sizeof(cases) / sizeof(cases[0]); ++i)
        if (cases[i].run())
            return 1;
    unsigned int improved = 0, matched = 0, fifo_requests = 0, packed_requests = 0;
    unsigned int fifo_bytes = 0, packed_bytes = 0, fifo_failed = 0, packed_failed = 0;
    unsigned int fifo_wait = 0, packed_wait = 0;
    unsigned int matched_fifo_requests = 0, matched_packed_requests = 0;
    unsigned int matched_fifo_bytes = 0, matched_packed_bytes = 0;
    unsigned int matched_fifo_attempted = 0, matched_packed_attempted = 0;
    unsigned int matched_fifo_padding = 0, matched_packed_padding = 0;
    unsigned int matched_upper = 0, matched_decode = 0;
    for (unsigned int i = 0; i < 48U; ++i) {
        struct costs fifo, packed;
        if (trace(i, false, &fifo) || trace(i, true, &packed))
            return 1;
        CHECK("identical_cpu", fifo.decode == packed.decode && fifo.compress == packed.compress && fifo.upper == packed.upper);
        /* Equal failure counts alone do not establish the same useful work. */
        if (!memcmp(fifo.successful_ids, packed.successful_ids, sizeof(fifo.successful_ids))) {
            ++matched;
            matched_fifo_requests += fifo.requests; matched_packed_requests += packed.requests;
            matched_fifo_bytes += fifo.written; matched_packed_bytes += packed.written;
            matched_fifo_attempted += fifo.attempted_bytes; matched_packed_attempted += packed.attempted_bytes;
            matched_fifo_padding += fifo.padding; matched_packed_padding += packed.padding;
            matched_upper += fifo.upper; matched_decode += fifo.decode;
            if (packed.requests < fifo.requests && packed.written < fifo.written)
                ++improved;
        }
        fifo_requests += fifo.requests; packed_requests += packed.requests;
        fifo_bytes += fifo.written; packed_bytes += packed.written;
        fifo_failed += fifo.failed; packed_failed += packed.failed;
        if (fifo.max_wait > fifo_wait) fifo_wait = fifo.max_wait;
        if (packed.max_wait > packed_wait) packed_wait = packed.max_wait;
    }
    CHECK("comparative_witness", improved > 0U && matched > 0U);
    printf("PASS traces=48 directed=9 matched=%u improved=%u fifo_requests=%u packed_requests=%u fifo_bytes=%u packed_bytes=%u fifo_failed=%u packed_failed=%u fifo_wait=%u packed_wait=%u model_bytes=%zu NOT_AUTH=1 PHASE_A=BLOCKED\n",
        matched, improved, fifo_requests, packed_requests, fifo_bytes, packed_bytes,
        fifo_failed, packed_failed, fifo_wait, packed_wait, sizeof(disk));
    printf("MATCHED fifo_requests=%u packed_requests=%u fifo_bytes=%u packed_bytes=%u fifo_attempted_bytes=%u packed_attempted_bytes=%u fifo_padding=%u packed_padding=%u upper_bytes=%u decode_each=%u compress_each=%u\n",
        matched_fifo_requests, matched_packed_requests, matched_fifo_bytes, matched_packed_bytes,
        matched_fifo_attempted, matched_packed_attempted, matched_fifo_padding, matched_packed_padding,
        matched_upper, matched_decode, matched_decode);
    return 0;
}
