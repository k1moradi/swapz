#!/usr/bin/env python3
"""R094 actual target helper extraction; all kernel/owner/lower boundaries are host adapters."""
import hashlib
import json
from pathlib import Path
import runpy
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "src/kernel/dm-target.c"
REGISTRY = ROOT / "tests/tools/round089-selected-dm-registry-verify.py"

ADAPTER = r'''
#include <stdlib.h>
#include <string.h>
typedef uint32_t u32;
typedef uint32_t swapz_u32;
typedef uint64_t swapz_u64;
typedef unsigned char swapz_u8;
typedef s64 atomic64_t;
#define ATOMIC64_INIT(x) (x)
#define U32_MAX UINT32_MAX
#define SWAPZ_BLOCK_BYTES 4096U
#define SWAPZ_MAX_COMPRESSED 3568U
#define SWAPZ_ROUND094_GENERATION_PAGES 16U
#define SWAPZ_ROUND094_BROKER_SLOTS 8U
#define list_empty(list) (!*(list))
#define mutex_lock(lock) do { assert(!*(lock)); *(lock)=true; } while (0)
#define mutex_unlock(lock) do { assert(*(lock)); *(lock)=false; } while (0)
struct dm_target { void *private; void *table; u64 begin; };
struct swapz_ticket_broker { unsigned int caps; };
struct swapz_ticket_cap { struct swapz_ticket_broker *broker; u64 session, epoch; };
struct swapz_map { u32 generation; };
struct swapz_authority { bool in_flight, batch_pending, batch_replaying, gc_allocation, attached; };
struct swapz_original_storage_ops {
    void *context;
    int (*write)(void *, u32, const swapz_u8 *, u32, u32 *);
    int (*read)(void *, u32, swapz_u8 *, u32, u32 *);
    int (*flush)(void *);
};
struct swapz_shared_storage { struct swapz_authority *authority; };
struct swapz_original_decoder_bridge { bool ready; };
struct swapz_dm {
    struct dm_target *target;
    bool queue_lock, accepting, failed, ordered_owner;
    bool incoming, preparation_incoming, preparation_queued, batch_count, inflight;
    struct { bool active; } gc_recovery;
    struct swapz_authority authority;
    struct swapz_map *maps;
    u32 logical_pages;
    struct swapz_round089_route original_route;
    struct swapz_ticket_cap original_cap, original_retired_cap;
    struct swapz_shared_storage *original_storage;
    struct swapz_original_decoder_bridge *original_decoder_bridge;
    swapz_u8 *original_decode_scratch, *original_decode_verified;
    u64 original_owner_session, original_owner_epoch, original_snapshot_epoch;
    u32 original_generations[SWAPZ_ROUND094_GENERATION_PAGES];
    bool original_trial, original_bridge_ready, original_storage_ready, original_owner_closing;
    int original_teardown_error;
};
static struct swapz_dm *observed;
static struct swapz_ticket_broker broker;
static u64 session;
static bool owner_live, owner_closed, owner_busy, refuse_open, refuse_bridge, refuse_storage;
static bool refuse_begin, refuse_storage_close;
static unsigned int allocations, allocation_calls, fail_allocation, capability_gets, capability_puts, begins, finishes;
static void *vzalloc(size_t bytes)
{
    assert(observed->ordered_owner && !observed->queue_lock);
    if (++allocation_calls == fail_allocation)
        return NULL;
    void *result = calloc(1, bytes);
    assert(result);
    ++allocations;
    return result;
}
static void vfree(void *address)
{
    assert(observed->ordered_owner && !observed->queue_lock);
    if (address) {
        assert(allocations);
        --allocations;
        free(address);
    }
}
static bool swapz_has_inflight(const struct swapz_dm *ctx) { return ctx->inflight; }
static int swapz_round090_storage_write(void *ctx, u32 block, const swapz_u8 *bytes,
                                       u32 length, u32 *completed)
{ (void)ctx; (void)block; (void)bytes; (void)length; (void)completed; abort(); }
static int swapz_round090_storage_read(void *ctx, u32 block, swapz_u8 *bytes,
                                      u32 length, u32 *completed)
{ (void)ctx; (void)block; (void)bytes; (void)length; (void)completed; abort(); }
static int swapz_round090_storage_flush(void *ctx) { (void)ctx; abort(); }
static int swapz_original_decoder_bridge_init(struct swapz_original_decoder_bridge *bridge,
    const struct swapz_original_storage_ops *lower, struct swapz_original_storage_ops *wrapped)
{
    assert(observed->ordered_owner && !observed->queue_lock);
    assert(lower->context == observed && lower->write == swapz_round090_storage_write &&
           lower->read == swapz_round090_storage_read && lower->flush == swapz_round090_storage_flush);
    if (refuse_bridge) return -EIO;
    bridge->ready = true;
    *wrapped = *lower;
    wrapped->context = bridge;
    return 0;
}
static int swapz_original_decoder_bridge_close(struct swapz_original_decoder_bridge *bridge)
{
    assert(observed->ordered_owner && !observed->queue_lock && bridge->ready);
    assert(!observed->authority.attached);
    bridge->ready = false;
    return 0;
}
static int swapz_shared_storage_init(struct swapz_shared_storage *storage,
    struct swapz_authority *authority, const struct swapz_original_storage_ops *wrapped)
{
    assert(observed->ordered_owner && !observed->queue_lock && !authority->attached);
    assert(wrapped->context == observed->original_decoder_bridge);
    if (refuse_storage) return -EIO;
    authority->attached = true;
    storage->authority = authority;
    return 0;
}
static int swapz_shared_storage_close(struct swapz_shared_storage *storage)
{
    assert(observed->ordered_owner && !observed->queue_lock && storage->authority->attached);
    if (refuse_storage_close) return -EBUSY;
    storage->authority->attached = false;
    return 0;
}
static int swapz_mm_broker_owner_open(u32 capacity, u32 max_length, u64 byte_limit,
                                     struct swapz_ticket_cap *cap)
{
    assert(!observed->ordered_owner && !observed->queue_lock);
    assert(capacity == 8U && max_length == 3568U && byte_limit == 8U * 3568U);
    if (owner_live || refuse_open) return -EBUSY;
    owner_live = true;
    owner_closed = false;
    broker.caps = 1U;
    ++capability_gets;
    ++session;
    *cap = (struct swapz_ticket_cap){&broker, session, session};
    return 0;
}
static int swapz_mm_broker_owner_begin_close(u64 owner_session, u64 epoch)
{
    assert(!observed->ordered_owner && !observed->queue_lock && owner_live);
    assert(owner_session == session && epoch == session);
    if (refuse_begin) return -EBUSY;
    owner_closed = true;
    ++begins;
    return 0;
}
static int swapz_ticket_broker_put(struct swapz_ticket_cap *cap)
{
    assert(!observed->ordered_owner && !observed->queue_lock && owner_closed);
    assert(cap->broker == &broker && broker.caps == 1U);
    broker.caps = 0;
    ++capability_puts;
    *cap = (struct swapz_ticket_cap){0};
    return 0;
}
static int swapz_mm_broker_owner_finish_close(u64 owner_session, u64 epoch)
{
    assert(!observed->ordered_owner && !observed->queue_lock && owner_live && owner_closed);
    assert(owner_session == session && epoch == session && !broker.caps);
    ++finishes;
    if (owner_busy) return -EBUSY;
    owner_live = false;
    return 0;
}
'''

TEST = r'''
static unsigned int checks;
/* Negative variants intentionally terminate at the first violated semantic
 * assertion, possibly with an outstanding allocation. Baseline success
 * returns normally, retaining leak-sanitizer checks. Never credit a
 * sanitizer failure or a crash as a semantic rejection.
 */
#define CHECK(x) do { ++checks; if (!(x)) { fprintf(stderr, "R094_ASSERT line=%d\n", __LINE__); fflush(stderr); _Exit(77); } } while (0)
static void late_refusal(void)
{
    if (observed->original_route.registration_epoch) {
        observed->accepting = false;
        before_lock = NULL;
    }
}
static void replacement_route(void)
{
    struct swapz_round089_route replacement = {0};
    if (!observed->original_route.registration_epoch)
        return;
    before_lock = NULL;
    observed->queue_lock = true;
    swapz_round089_revoke_route_locked(observed);
    observed->queue_lock = false;
    assert(swapz_round089_register_route(observed->target, 777U, 888U, 999U, &replacement) == 0);
}
static void refresh(struct swapz_dm *ctx)
{
    mutex_lock(&ctx->ordered_owner);
    swapz_round094_publish_generations(ctx);
    mutex_unlock(&ctx->ordered_owner);
}
static bool next(struct swapz_dm *ctx, u64 logical, u64 *generation)
{
    bool ok;
    ctx->queue_lock = true;
    ok = swapz_round094_snapshot_next_locked(ctx, logical, generation);
    ctx->queue_lock = false;
    return ok;
}
static void detach(struct swapz_dm *ctx)
{
    ctx->queue_lock = true;
    swapz_round089_revoke_route_locked(ctx);
    swapz_round094_invalidate_locked(ctx);
    ctx->original_retired_cap = ctx->original_cap;
    ctx->original_cap = (struct swapz_ticket_cap){0};
    ctx->queue_lock = false;
}
int main(void)
{
    int table = 0;
    struct swapz_map maps[18] = {{0}};
    struct swapz_dm ctx = {.accepting=true, .original_trial=true, .maps=maps, .logical_pages=18U};
    struct dm_target ti = {&ctx, &table, 0};
    u64 generation = 99U, old_route, old_session;
    ctx.target = &ti;
    observed = &ctx;
    for (unsigned int index = 1U; index <= 4U; ++index) {
        allocation_calls = 0;
        fail_allocation = index;
        CHECK(swapz_round094_setup(&ctx) == -ENOMEM);
        CHECK(!allocations && !owner_live && !ctx.original_storage && !ctx.original_decoder_bridge);
    }
    fail_allocation = 0;
    refuse_bridge = true;
    CHECK(swapz_round094_setup(&ctx) == -EIO);
    CHECK(!allocations && !owner_live && !ctx.authority.attached);
    refuse_bridge = false;
    refuse_storage = true;
    CHECK(swapz_round094_setup(&ctx) == -EIO);
    CHECK(!allocations && !owner_live && !ctx.authority.attached);
    refuse_storage = false;
    refuse_open = true;
    CHECK(swapz_round094_setup(&ctx) == -EBUSY);
    CHECK(!allocations && !owner_live && !ctx.authority.attached);
    refuse_open = false;
    before_lock = late_refusal;
    CHECK(swapz_round094_setup(&ctx) == -ESTALE);
    CHECK(!ctx.original_route.registration_epoch && !ctx.original_cap.broker);
    CHECK(!allocations && !owner_live && capability_gets == capability_puts && !ctx.authority.attached);
    ctx.accepting = true;
    before_lock = replacement_route;
    CHECK(swapz_round094_setup(&ctx) == -ESTALE);
    CHECK(ctx.original_route.registration_epoch && ctx.original_route.target_epoch == 999U);
    CHECK(!ctx.original_cap.broker && !allocations && !owner_live && capability_gets == capability_puts);
    ctx.queue_lock = true;
    swapz_round089_revoke_route_locked(&ctx);
    ctx.queue_lock = false;
    maps[1].generation = 41U;
    maps[16].generation = U32_MAX;
    CHECK(swapz_round094_setup(&ctx) == 0);
    CHECK(allocations == 4U && owner_live && broker.caps == 1U && ctx.authority.attached);
    old_session = ctx.original_owner_session;
    old_route = ctx.original_route.registration_epoch;
    CHECK(next(&ctx, 1U, &generation) && generation == 42U);
    CHECK(!next(&ctx, 0U, &generation) && !next(&ctx, 16U, &generation) &&
          !next(&ctx, 17U, &generation) && generation == 42U);
    CHECK(swapz_round094_setup(&ctx) == -EALREADY && broker.caps == 1U);
    ctx.queue_lock = true;
    swapz_round094_invalidate_locked(&ctx);
    ctx.queue_lock = false;
    maps[1].generation++;
    CHECK(!next(&ctx, 1U, &generation));
    ctx.incoming = true;
    refresh(&ctx);
    CHECK(!next(&ctx, 1U, &generation));
    ctx.incoming = false;
    ctx.authority.gc_allocation = true;
    refresh(&ctx);
    CHECK(!next(&ctx, 1U, &generation));
    ctx.authority.gc_allocation = false;
    ctx.inflight = true;
    refresh(&ctx);
    CHECK(!next(&ctx, 1U, &generation));
    ctx.inflight = false;
    ctx.authority.batch_pending = true;
    refresh(&ctx);
    CHECK(!next(&ctx, 1U, &generation));
    ctx.authority.batch_pending = false;
    refresh(&ctx);
    CHECK(next(&ctx, 1U, &generation) && generation == 43U);
    ctx.original_route.registration_epoch++;
    CHECK(!next(&ctx, 1U, &generation));
    detach(&ctx);
    CHECK(!next(&ctx, 1U, &generation));
    refuse_begin = true;
    CHECK(swapz_round094_close_owner(&ctx, &ctx.original_retired_cap, false) == -EBUSY);
    CHECK(owner_live && !owner_closed && broker.caps == 1U && ctx.original_retired_cap.broker);
    refuse_begin = false;
    CHECK(swapz_round094_close_owner(&ctx, &ctx.original_retired_cap, false) == 0);
    CHECK(owner_live && owner_closed && !broker.caps && ctx.original_owner_session == old_session);
    owner_busy = true;
    CHECK(swapz_round094_close_owner(&ctx, &ctx.original_retired_cap, true) == -EBUSY);
    CHECK(owner_live && owner_closed && ctx.original_owner_session == old_session);
    mutex_lock(&ctx.ordered_owner);
    refuse_storage_close = true;
    CHECK(swapz_round094_close_storage(&ctx) == -EBUSY);
    CHECK(allocations == 4U && ctx.authority.attached && ctx.original_bridge_ready);
    refuse_storage_close = false;
    CHECK(swapz_round094_close_storage(&ctx) == 0);
    mutex_unlock(&ctx.ordered_owner);
    CHECK(!allocations && !ctx.authority.attached);
    CHECK(swapz_round094_setup(&ctx) == -EBUSY);
    owner_busy = false;
    CHECK(swapz_round094_setup(&ctx) == 0);
    CHECK(ctx.original_owner_session > old_session && ctx.original_route.registration_epoch > old_route);
    CHECK(next(&ctx, 1U, &generation) && generation == 43U);
    detach(&ctx);
    CHECK(swapz_round094_close_owner(&ctx, &ctx.original_retired_cap, true) == 0);
    mutex_lock(&ctx.ordered_owner);
    CHECK(swapz_round094_close_storage(&ctx) == 0);
    mutex_unlock(&ctx.ordered_owner);
    CHECK(!allocations && !owner_live && capability_gets == capability_puts && begins == capability_gets && finishes >= begins);
    printf("ROUND094_TARGET_PASS checks=%u AUTH=0 host_boundary_only\n", checks);
    return 0;
}
'''

def main():
    evidence = Path(sys.argv[1])
    evidence.mkdir(parents=True, exist_ok=True)
    report = {"AUTH": 0, "native": False, "first_error": None, "compilers": {}}
    try:
        registry = runpy.run_path(str(REGISTRY))
        source = registry["read_source"]()
        extract = registry["extract"]
        record = extract(source, "struct swapz_round089_route {", "/* Globally non-reused")
        revoke = registry["extract_revoke"](source)
        routes = extract(source, "static __maybe_unused int swapz_round089_register_route(",
                         "/* Original core validation runs")
        def fragment(name):
            begin = f"/* ROUND094_{name}_BEGIN */"
            end = f"/* ROUND094_{name}_END */"
            return extract(source, begin, end)
        generation = fragment("GENERATION")
        close = fragment("OWNER_CLOSE")
        setup = fragment("SETUP")
        assert "swapz_round091_ordered_claim_permitted(void)\n{\n\treturn false;\n}" in source
        admission = extract(source, "static int swapz_map(struct dm_target *ti, struct bio *bio)",
                            "static void swapz_drain(")
        assert admission.index("swapz_round094_invalidate_locked(ctx);") < admission.index(
            "list_add_tail(&entry->list, &ctx->incoming);")
        worker = extract(source, "static void swapz_worker(struct work_struct *work)\n{",
                         "/*\n * ID175 idle-lane")
        assert worker.index("swapz_round094_invalidate_locked(ctx);") < worker.index("swapz_worker_pass(ctx);")
        assert worker.index("swapz_worker_pass(ctx);") < worker.index("swapz_round094_publish_generations(ctx);")
        assert worker.index("swapz_round094_publish_generations(ctx);") < worker.index("mutex_unlock(&ctx->ordered_owner);")
        resume = extract(source, "static void swapz_resume(struct dm_target *ti)\n{",
                         "static void swapz_free(")
        drain = extract(source, "static void swapz_drain(struct dm_target *ti)\n{",
                        "static void swapz_resume(")
        assert resume.index("queue_work(system_unbound_wq, &ctx->original_setup_work);") < resume.index(
            "flush_work(&ctx->original_setup_work);")
        assert drain.index("swapz_round090_unpublish_target(ctx);") < drain.index(
            "drain_workqueue(ctx->workqueue);") < drain.index(
            "flush_work(&ctx->original_release_work);") < drain.index(
            "flush_work(&ctx->original_teardown_work);")
        destructor = extract(source, "static void swapz_dtr(struct dm_target *ti)\n{",
                             "static u64 swapz_authority_metadata_ram_bytes(")
        assert destructor.count("ti->private = NULL;") == 1
        assert destructor.index("swapz_drain(ti);") < destructor.index("swapz_free(ctx);")
        assert destructor.index("goto detach;") < destructor.index("swapz_free(ctx);")
        assert destructor.index("swapz_free(ctx);") < destructor.index("detach:") < destructor.index(
            "ti->private = NULL;")
        assert "ctx->original_trial = is_nullb && !ctx->physical_backing;" in source
        assert "swapz_round094_setup(ctx)" in source and "swapz_round094_teardown_work" in source
        def mutate(code, old, new):
            if code.count(old) != 1:
                raise RuntimeError("mutation anchor drift: " + old)
            return code.replace(old, new, 1)
        combined = generation + close + setup
        variants = {
            "baseline": combined,
            "no_generation_invalidate": mutate(combined, "ctx->original_snapshot_epoch = 0;", "(void)ctx;"),
            "ignore_pending_fifo": mutate(combined, "list_empty(&ctx->incoming) &&", "true &&"),
            "ignore_gc": mutate(combined, "!ctx->authority.gc_allocation &&", "true &&"),
            "ignore_route_epoch": mutate(combined, "ctx->original_snapshot_epoch != ctx->original_route.registration_epoch ||", "false ||"),
            "no_install_rollback": mutate(combined,
                "if (swapz_round089_route_matches_locked(ctx, &route))\n\t\t\tswapz_round089_revoke_route_locked(ctx);",
                "(void)route;"),
            "erase_replacement_route": mutate(combined,
                "if (swapz_round089_route_matches_locked(ctx, &route))\n\t\t\tswapz_round089_revoke_route_locked(ctx);",
                "swapz_round089_revoke_route_locked(ctx);"),
        }
        report["fragment_sha256"] = hashlib.sha256(combined.encode()).hexdigest()
        with tempfile.TemporaryDirectory(prefix="round094-target-") as directory:
            program = Path(directory) / "target.c"
            binary = program.with_suffix("")
            for compiler in ("gcc", "clang"):
                result = {"checks": None, "mutants": []}
                report["compilers"][compiler] = result
                for name, variant in variants.items():
                    program.write_text(registry["ADAPTER"] + record + ADAPTER + revoke + routes + variant + TEST)
                    subprocess.run([compiler, "-std=gnu11", "-O1", "-g", "-Wall", "-Wextra",
                                    "-Wconversion", "-Wshadow", "-Werror", "-fsanitize=address,undefined",
                                    "-fno-sanitize-recover=all", "-fno-pie", "-no-pie", str(program), "-o", str(binary)], check=True, timeout=30)
                    run = subprocess.run([str(binary)], capture_output=True, text=True, timeout=10)
                    if name == "baseline":
                        if run.returncode or run.stderr or not run.stdout.startswith("ROUND094_TARGET_PASS checks="):
                            raise RuntimeError(f"{compiler} baseline: {run.returncode} {run.stderr[:500]}")
                        result["checks"] = int(run.stdout.split("checks=")[1].split()[0])
                        print(compiler, run.stdout, end="")
                    else:
                        if run.returncode != 77 or run.stdout or not run.stderr.startswith("R094_ASSERT line=") or len(run.stderr.splitlines()) != 1:
                            raise RuntimeError(f"{compiler} mutant {name}: {run.returncode} {run.stderr[:500]}")
                        result["mutants"].append(name)
                        print(f"ROUND094_TARGET_MUTANT_KILLED compiler={compiler} name={name}")
        return 0
    except (RuntimeError, AssertionError, OSError, subprocess.SubprocessError, ValueError) as error:
        report["first_error"] = str(error)
        print(report["first_error"], file=sys.stderr)
        return 1
    finally:
        (evidence / "target-owner.json").write_text(json.dumps(report, indent=2) + "\n")


if __name__ == "__main__":
    sys.exit(main())
