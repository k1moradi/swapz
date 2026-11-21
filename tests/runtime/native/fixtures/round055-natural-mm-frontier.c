/* SPDX-License-Identifier: GPL-2.0-only */
/* Rootless counterfactual service scheduler; reuse the tested RAM disk/ACK model. */
#define main round054_model_main
#include "round054-natural-mm-coalescing.c"
#undef main

enum policy { FIFO, READY_ONLY, ADAPTIVE, POLICIES };
enum { HOLD = 2, RETRIES = 2, HORIZON = 512, FIRST_ID = 8, MAX_SERVICE = 6 };
enum { READ_FENCE = 1, FLUSH_FENCE = 2, GC_FENCE = 4 };
struct arrival { unsigned int tick, length, slot; bool eio, cancel; };
struct scenario {
    const char *name;
    unsigned int pattern, capacity, reserve, service, gc_tick, close_tick;
    bool gc_fail;
};
struct observation {
    unsigned int arrival_count, rejected, retries, retry_exhausted, fence_wait;
    unsigned int queue_wait[EVENTS], service_wait[EVENTS], hold[EVENTS];
    unsigned int max_hold, completed_requests, completed_bytes, committed_requests;
    unsigned int gc_attempted, gc_read, gc_fail, read_fences, flush_fences;
    unsigned int max_retained, drain_tick;
    struct costs cost;
};
struct flight {
    unsigned int due, launched, count;
    struct map previous[PACK];
    bool gc;
};
static struct arrival arrivals[EVENTS];
static struct observation observation;
static struct flight flight;

static unsigned int free_foreground_blocks(void)
{
    unsigned int free_blocks = 0;
    for (unsigned int i = 1; i < disk.capacity; ++i)
        if (!disk.used[i] && !reserved(i))
            ++free_blocks;
    return free_blocks;
}
/* Only already admitted normal work is visible. A lone page, a fence,
 * capacity pressure, a full queue or a closed/noncurrent head never waits. */
static bool adaptive_hold(unsigned int fences, unsigned int recent)
{
    if (!disk.count || disk.active.active || fences || recent < 2U ||
        disk.count >= QUEUE || free_foreground_blocks() <= 4U ||
        !current(&disk.pending[0]) || disk.tick - disk.pending[0].arrival >= HOLD)
        return false;
    unsigned int count = plan_count();
    if (count < 2U || count >= PACK || count != disk.count)
        return false;
    unsigned int payload = 0;
    for (unsigned int i = 0; i < count; ++i)
        payload += payload_length(&disk.pending[i]);
    unsigned int bytes = payload <= SWAPZ_BLOCK_BYTES ? SWAPZ_BLOCK_BYTES :
        payload <= 2U * SWAPZ_BLOCK_BYTES ? 2U * SWAPZ_BLOCK_BYTES : 4U * SWAPZ_BLOCK_BYTES;
    return bytes - payload >= 512U && bytes <= count * SWAPZ_BLOCK_BYTES;
}
static unsigned int service_ticks(unsigned int profile, unsigned int id, unsigned int blocks)
{
    if (profile == 0U)
        return 1U;
    if (profile == 1U)
        return 2U + blocks;
    return 1U + (id * 13U % 4U) + blocks / 2U;
}
static bool same_map(const struct map *a, const struct map *b)
{
    return a->live == b->live && a->start == b->start && a->blocks == b->blocks &&
        a->offset == b->offset && a->length == b->length && a->generation == b->generation && a->id == b->id;
}
static bool prior_readable(const struct map *old, unsigned int slot)
{
    return same_map(old, &disk.maps[slot]) && (!old->live || map_matches(slot, old->id, old->length));
}
static int launch(unsigned int profile)
{
    unsigned int head_id = disk.pending[0].id;
    unsigned int head_wait = disk.tick - disk.pending[0].arrival;
    int error = stage();
    if (error) {
        CHECK("bounded_stage_failure", error == -ENOSPC || error == -ECANCELED);
        observation.queue_wait[head_id] = head_wait;
        return 0;
    }
    flight = (struct flight){ .due = disk.tick + service_ticks(profile, head_id, disk.active.blocks),
        .launched = disk.tick, .count = disk.active.count };
    for (unsigned int i = 0; i < flight.count; ++i) {
        const struct event *event = &disk.pending[i];
        flight.previous[i] = disk.maps[event->slot];
        observation.queue_wait[event->id] = disk.tick - event->arrival;
        CHECK("full_upper_at_launch", full_page(event));
        CHECK("no_early_ack", !disk.ack[event->id] && prior_readable(&flight.previous[i], event->slot));
    }
    return 0;
}
static int retire_flight(void)
{
    if (!disk.active.active || disk.tick < flight.due)
        return 0;
    unsigned int ids[PACK], slots[PACK], lengths[PACK];
    for (unsigned int i = 0; i < flight.count; ++i) {
        const struct event *event = &disk.pending[i];
        ids[i] = event->id; slots[i] = event->slot; lengths[i] = payload_length(event);
        CHECK("no_early_ack", !disk.ack[event->id] && prior_readable(&flight.previous[i], event->slot));
        observation.service_wait[event->id] = disk.tick - flight.launched;
    }
    unsigned int token = disk.active.token;
    unsigned int lower_bytes = disk.active.blocks * SWAPZ_BLOCK_BYTES;
    bool durable = true;
    for (unsigned int i = 0; i < flight.count; ++i)
        durable = durable && !disk.pending[i].eio;
    CHECK("late_callback_refusal", complete(token - 1U, true) == -ESTALE);
    int error = complete(token, durable);
    CHECK("terminal_lower", error == 0 || error == -EIO);
    /* Durability and map publication are distinct, including teardown aborts. */
    if (durable) {
        ++observation.completed_requests;
        observation.completed_bytes += lower_bytes;
    }
    observation.committed_requests += error == 0;
    for (unsigned int i = 0; i < flight.count; ++i) {
        CHECK("one_terminal_ack", disk.ack[ids[i]] == 1U);
        if (error)
            CHECK("rollback_full_page", prior_readable(&flight.previous[i], slots[i]));
        else
            CHECK("successful_readback", map_matches(slots[i], ids[i], lengths[i]));
    }
    CHECK("duplicate_callback_refusal", complete(token, true) == -ESTALE);
    return 0;
}
/* Reserve only an equal-size contiguous COW destination. Seed setup is identical
 * within each policy comparison, excluded from trace counts. */
static int setup(const struct scenario *scenario, enum policy policy)
{
    reset(scenario->capacity, true);
    disk.reserve_blocks = scenario->reserve;
    disk.reserve = disk.capacity - disk.reserve_blocks;
    unsigned int seed = scenario->gc_tick ? scenario->reserve : 1U;
    CHECK("seed_geometry", seed == 1U || seed == 2U || seed == 4U);
    for (unsigned int id = 1; id <= seed; ++id) {
        struct event event = event_at(id, id, seed == 1U ? 0U : 3000U);
        CHECK("seed_admission", admit(&event) == 0);
    }
    CHECK("seed_commit", stage() == 0 && disk.active.blocks == seed && complete(disk.active.token, true) == 0);
    memset(&disk.cost, 0, sizeof(disk.cost));
    memset(&observation, 0, sizeof(observation));
    memset(&flight, 0, sizeof(flight));
    disk.coalesce = policy != FIFO;
    return 0;
}
/* External immutable trace; retry harness, not retained scheduler payload. */
static unsigned int generate(const struct scenario *scenario)
{
    unsigned int next = FIRST_ID;
    const unsigned int lengths[] = {700U, 1900U, 3000U, 3568U, 3569U, 0U};
    for (unsigned int tick = 1; tick <= 20U; ++tick) {
        unsigned int count = 0;
        switch (scenario->pattern) {
        case 0: count = tick % 4U == 1U ? 1U : 0U; break; /* sparse */
        case 1: count = tick % 3U == 1U ? 4U : 0U; break; /* ready burst */
        case 2: count = tick % 4U < 2U ? 2U : 0U; break; /* two-tick burst */
        case 3: count = tick % 2U ? 3U : 1U; break; /* overload */
        default: count = tick % 3U ? 1U : 3U; break; /* mixed */
        }
        for (unsigned int i = 0; i < count; ++i) {
            unsigned int length = scenario->pattern < 3U ? 700U : lengths[(next * 7U) % 6U];
            arrivals[next] = (struct arrival){ .tick = tick, .length = length,
                .slot = 8U + (next % 24U), .eio = scenario->pattern >= 3U && next % 11U == 0U,
                .cancel = scenario->pattern == 4U && next % 13U == 0U };
            ++next;
        }
    }
    return next;
}
static int run_trace(const struct scenario *scenario, enum policy policy, struct observation *out)
{
    if (setup(scenario, policy))
        return 1;
    unsigned int end = generate(scenario), next = FIRST_ID, retried = 0, fences = 0, previous_recent = 0;
    CHECK("trace_bound", end < EVENTS);
    observation.arrival_count = end - FIRST_ID;
    for (disk.tick = 1; disk.tick < HORIZON; ++disk.tick) {
        if (disk.tick == 7U && scenario->pattern >= 3U) fences |= READ_FENCE;
        if (disk.tick == 13U && scenario->pattern >= 3U) fences |= FLUSH_FENCE;
        if (disk.tick == scenario->gc_tick) fences |= GC_FENCE;
        if (disk.tick == scenario->close_tick) disk.closed = true;
        if (retire_flight()) return 1;
        if (flight.gc && disk.tick >= flight.due) {
            int error = relocate(1U, !scenario->gc_fail);
            CHECK("gc_terminal", error == (scenario->gc_fail ? -EIO : 0));
            observation.gc_fail += error != 0;
            CHECK("gc_seed_readable", map_matches(1U, 1U, scenario->reserve == 1U ? SWAPZ_BLOCK_BYTES : 3000U));
            flight.gc = false;
            fences &= ~(unsigned int)GC_FENCE;
        }
        unsigned int recent = 0;
        /* Strict external FIFO, finite retry of oldest refused arrival only. */
        while (next < end && arrivals[next].tick <= disk.tick) {
            struct arrival input = arrivals[next];
            struct event event = event_at(next, input.slot, input.length);
            event.eio = input.eio; event.cancel = input.cancel;
            int error = fences ? -EAGAIN : admit(&event);
            if (error == -EAGAIN) {
                ++observation.rejected;
                observation.fence_wait += fences != 0U;
                if (retried < RETRIES) { ++retried; ++observation.retries; break; }
                ++observation.retry_exhausted;
            } else if (!error) {
                ++recent;
            } else {
                CHECK("closed_admission", error == -EINVAL && disk.closed);
                ++observation.retry_exhausted;
            }
            ++next; retried = 0;
        }
        if (!disk.active.active && !flight.gc) {
            if (!disk.count && fences) {
                if (fences & READ_FENCE) {
                    CHECK("read_fence", map_matches(1U, 1U, scenario->gc_tick && scenario->reserve > 1U ? 3000U : SWAPZ_BLOCK_BYTES));
                    ++observation.read_fences; fences &= ~(unsigned int)READ_FENCE;
                } else if (fences & FLUSH_FENCE) {
                    ++observation.flush_fences; fences &= ~(unsigned int)FLUSH_FENCE;
                } else {
                    CHECK("gc_reserve", scenario->reserve && !disk.active.active && !disk.count);
                    observation.gc_attempted += scenario->reserve * SWAPZ_BLOCK_BYTES;
                    observation.gc_read += scenario->reserve * SWAPZ_BLOCK_BYTES;
                    flight = (struct flight){ .gc = true, .due = disk.tick + service_ticks(scenario->service, 1U, scenario->reserve) };
                }
            } else if (disk.count) {
                if (policy == ADAPTIVE && adaptive_hold(fences, recent + previous_recent)) {
                    for (unsigned int i = 0; i < disk.count; ++i) {
                        unsigned int held = ++observation.hold[disk.pending[i].id];
                        if (held > observation.max_hold) observation.max_hold = held;
                    }
                } else if (launch(scenario->service)) return 1;
            }
        }
        previous_recent = recent;
        unsigned int retained = disk.cost.max_queue * SWAPZ_BLOCK_BYTES;
        if (retained > observation.max_retained) observation.max_retained = retained;
        CHECK("bounded_retention", disk.count <= QUEUE && observation.max_hold <= HOLD && intact());
        if (next == end && !disk.count && !disk.active.active && !flight.gc && !fences && disk.tick > 20U && disk.tick >= scenario->gc_tick) break;
    }
    CHECK("finite_drain", disk.tick < HORIZON && next == end && !disk.count && !disk.active.active && !flight.gc);
    for (unsigned int id = FIRST_ID; id < end; ++id)
        CHECK("accepted_only_ack", disk.ack[id] == (unsigned int)disk.accepted[id] &&
            observation.queue_wait[id] <= QUEUE * MAX_SERVICE + HOLD && observation.service_wait[id] <= MAX_SERVICE);
    CHECK("actual_cpu_work", disk.cost.decode == disk.cost.compress && disk.cost.upper == disk.cost.decode * SWAPZ_BLOCK_BYTES &&
        disk.cost.success + disk.cost.failed == disk.cost.decode && disk.cost.decode + observation.retry_exhausted == observation.arrival_count);
    CHECK("accounted_writes", disk.cost.written == disk.cost.payload + disk.cost.padding &&
        observation.completed_requests <= disk.cost.requests && observation.gc_fail <= disk.cost.gc_requests &&
        observation.committed_requests <= observation.completed_requests && disk.cost.written <= observation.completed_bytes &&
        observation.completed_bytes <= disk.cost.attempted_bytes);
    observation.cost = disk.cost;
    observation.drain_tick = disk.tick;
    *out = observation;
    return 0;
}
static unsigned int percentile(const struct observation *value, bool service, unsigned int percent)
{
    unsigned int histogram[HORIZON] = {0};
    unsigned int count = 0;
    /* Rejected events have no upper ACK. An accepted zero-time failure counts. */
    for (unsigned int id = FIRST_ID; id < EVENTS; ++id) {
        unsigned int wait = service ? value->service_wait[id] : value->queue_wait[id];
        if (wait) { ++histogram[wait]; ++count; }
    }
    unsigned int zero = value->cost.decode - count;
    histogram[0] = zero;
    unsigned int rank = (value->cost.decode * percent + 99U) / 100U, cumulative = 0;
    for (unsigned int tick = 0; tick < HORIZON; ++tick) {
        cumulative += histogram[tick];
        if (cumulative >= rank) return tick;
    }
    return HORIZON;
}
static int decisions(void)
{
    reset(16U, true);
    struct event one = event_at(1U, 1U, 700U), two = event_at(2U, 2U, 700U);
    CHECK("decision_admission", admit(&one) == 0);
    CHECK("singleton_now", !adaptive_hold(0U, 2U));
    CHECK("decision_admission", admit(&two) == 0);
    CHECK("useful_hold", adaptive_hold(0U, 2U));
    CHECK("fence_now", !adaptive_hold(FLUSH_FENCE, 2U));
    CHECK("no_observed_burst", !adaptive_hold(0U, 1U));
    mark(1U, 7U, true);
    CHECK("pressure_now", !adaptive_hold(0U, 2U));
    mark(1U, 7U, false);
    disk.tick = HOLD;
    CHECK("hard_deadline", !adaptive_hold(0U, 2U));
    return 0;
}
static int timed_rollback(void)
{
    const struct scenario scenario = {"rollback", 0U, 16U, 1U, 1U, 0U, 0U, false};
    CHECK("timed_setup", setup(&scenario, READY_ONLY) == 0);
    struct event event = event_at(FIRST_ID, 1U, 3569U);
    event.eio = true;
    CHECK("timed_admit", admit(&event) == 0 && launch(1U) == 0);
    disk.tick = flight.due - 1U;
    CHECK("service_not_early", retire_flight() == 0 && disk.active.active && !disk.ack[FIRST_ID]);
    disk.tick = flight.due;
    CHECK("timed_rollback", retire_flight() == 0 && map_matches(1U, 1U, SWAPZ_BLOCK_BYTES));
    event = event_at(FIRST_ID + 1U, 1U, 3569U);
    CHECK("retry_admit", admit(&event) == 0 && launch(1U) == 0);
    disk.tick = flight.due;
    CHECK("timed_retry", retire_flight() == 0 && map_matches(1U, FIRST_ID + 1U, SWAPZ_BLOCK_BYTES) && intact());
    event = event_at(FIRST_ID + 2U, 1U, 0U);
    CHECK("teardown_admit", admit(&event) == 0 && launch(1U) == 0);
    disk.closed = true;
    disk.tick = flight.due;
    CHECK("durable_aborted_accounting", retire_flight() == 0 && observation.completed_requests == 2U &&
        observation.committed_requests == 1U && observation.completed_bytes == 2U * SWAPZ_BLOCK_BYTES &&
        disk.cost.written == SWAPZ_BLOCK_BYTES && map_matches(1U, FIRST_ID + 1U, SWAPZ_BLOCK_BYTES));
    return 0;
}
static const struct scenario scenarios[] = {
    {"sparse_fast", 0, 64, 0, 0, 0, 0, false},
    {"ready_burst_fast", 1, 64, 0, 0, 0, 0, false},
    {"paired_fast", 2, 64, 0, 0, 0, 0, false},
    {"paired_slow", 2, 64, 0, 1, 0, 0, false},
    {"paired_variable", 2, 64, 0, 2, 0, 0, false},
    {"overload_variable", 3, 32, 0, 2, 0, 0, false},
    {"mixed_capacity_0", 4, 16, 0, 2, 0, 0, false},
    {"mixed_capacity_1", 4, 16, 1, 2, 0, 0, false},
    {"mixed_capacity_4", 4, 16, 4, 2, 0, 0, false},
    {"gc_raw", 4, 16, 1, 1, 10, 0, false},
    {"gc_two", 4, 32, 2, 2, 10, 0, false},
    {"gc_four_eio", 4, 64, 4, 2, 10, 0, true},
    {"target_close", 3, 32, 1, 1, 0, 12, false},
};
int main(int argc, char **argv)
{
    if (argc == 2) {
        if (!strcmp(argv[1], "decisions")) return decisions();
        if (!strcmp(argv[1], "rollback")) return timed_rollback();
        return 2;
    }
    CHECK("no_auth", SOURCE_MAPPED_AUTHENTICATED == 0 && DIRECT_COMPRESSED_HANDOFF == 0 && FORCED_RAW_BYPASS == 0);
    if (decisions() || timed_rollback()) return 1;
    for (unsigned int i = 0; i < sizeof(scenarios) / sizeof(scenarios[0]); ++i) {
        struct observation results[POLICIES];
        const struct scenario *scenario = &scenarios[i];
        for (enum policy policy = FIFO; policy < POLICIES; ++policy) {
            if (run_trace(scenario, policy, &results[policy])) return 1;
            const struct observation *r = &results[policy];
            printf("TRACE %s policy=%u usable=%u arrivals=%u accepted=%u success=%u failed=%u dropped=%u retries=%u refused=%u req=%u completed_req=%u committed_req=%u attempted=%u lower_completed=%u written=%u padding=%u gc_req=%u gc_attempted=%u gc_written=%u gc_read=%u gc_fail=%u total_attempted_req=%u total_completed_req=%u total_attempted=%u total_completed=%u read_fences=%u flush_fences=%u fence_refusals=%u peak_payload=%u queue_p95=%u queue_max=%u service_p95=%u service_max=%u hold_max=%u ack_max=%u drain=%u ids=%016llx:%016llx\n",
                scenario->name, (unsigned int)policy, scenario->capacity - 1U - scenario->reserve,
                r->arrival_count, r->cost.decode, r->cost.success, r->cost.failed, r->retry_exhausted,
                r->retries, r->rejected, r->cost.requests, r->completed_requests, r->committed_requests, r->cost.attempted_bytes, r->completed_bytes, r->cost.written, r->cost.padding,
                r->cost.gc_requests, r->gc_attempted, r->cost.gc_bytes, r->gc_read, r->gc_fail,
                r->cost.requests + 2U * r->cost.gc_requests,
                r->completed_requests + 2U * r->cost.gc_requests - r->gc_fail,
                r->cost.attempted_bytes + r->gc_attempted + r->gc_read,
                r->completed_bytes + r->cost.gc_bytes + r->gc_read, r->read_fences, r->flush_fences, r->fence_wait,
                r->max_retained, percentile(r, false, 95U), percentile(r, false, 100U), percentile(r, true, 95U), percentile(r, true, 100U),
                r->max_hold, r->cost.max_wait, r->drain_tick, (unsigned long long)r->cost.successful_ids[0], (unsigned long long)r->cost.successful_ids[1]);
        }
    }
    printf("PASS frontier scenarios=%zu policies=3 pending_bytes=%zu pending_metadata=%zu NOT_AUTH=1 PHASE_A=BLOCKED\n",
        sizeof(scenarios) / sizeof(scenarios[0]), sizeof(disk.pending), sizeof(disk.pending) - QUEUE * SWAPZ_BLOCK_BYTES);
    return 0;
}
