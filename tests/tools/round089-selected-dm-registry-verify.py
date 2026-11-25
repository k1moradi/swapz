#!/usr/bin/env python3
"""Extract actual target registry functions; host adapters are not kernel locks."""
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "src/kernel/dm-target.c"


def extract(source, begin, end):
    if source.count(begin) != 1:
        raise SystemExit("source extraction anchor drift: " + begin)
    tail = source.split(begin, 1)[1]
    if end not in tail:
        raise SystemExit("source extraction end missing: " + end)
    return begin + tail.split(end, 1)[0]


ADAPTER = r'''
#include <stdbool.h>
#include <stdint.h>
#include <errno.h>
#include <assert.h>
#include <stddef.h>
#include <stdio.h>
typedef uint64_t u64;
typedef int64_t s64;
#define S64_MAX INT64_MAX
#define __maybe_unused
#define READ_ONCE(x) (x)
#define lockdep_assert_held(lock) assert(*(lock))
/* Optional deterministic interleaving before acquisition, host only. */
static void (*before_lock)(void);
#define spin_lock_irqsave(lock, flags) do { assert(!*(lock)); if (before_lock) before_lock(); *(lock)=true; (flags)=0; } while (0)
#define spin_unlock_irqrestore(lock, flags) do { assert(*(lock)); *(lock)=false; (void)(flags); } while (0)
static s64 swapz_round089_route_sequence;
static bool contend;
static s64 atomic64_read(const s64 *sequence) { return *sequence; }
static s64 atomic64_cmpxchg(s64 *sequence, s64 old, s64 next)
{
    if (contend) {
        *sequence = next;
        return next;
    }
    s64 observed = *sequence;
    if (observed == old)
        *sequence = next;
    return observed;
}
'''
CONTEXT = r'''
struct dm_target { void *private; void *table; u64 begin; };
struct swapz_ticket_broker { u64 session, epoch; unsigned int caps; bool refuse; };
struct swapz_ticket_cap { struct swapz_ticket_broker *broker; u64 session, epoch; };
struct swapz_dm {
    struct dm_target *target;
    bool queue_lock, accepting, failed;
    struct swapz_round089_route original_route;
    struct swapz_ticket_cap original_cap;
};
static struct swapz_dm *observed_ctx;
static unsigned int cap_gets, cap_puts;
#define WARN_ON_ONCE(x) assert(!(x))
static int swapz_ticket_broker_try_get(struct swapz_ticket_broker *broker,
                                     u64 session, u64 epoch,
                                     struct swapz_ticket_cap *cap)
{
    assert(observed_ctx && !observed_ctx->queue_lock);
    if (!broker || broker->refuse || broker->session != session || broker->epoch != epoch)
        return -ESTALE;
    ++broker->caps;
    ++cap_gets;
    *cap = (struct swapz_ticket_cap){broker, session, epoch};
    return 0;
}
static int swapz_ticket_broker_put(struct swapz_ticket_cap *cap)
{
    assert(observed_ctx && !observed_ctx->queue_lock && cap->broker && cap->broker->caps);
    --cap->broker->caps;
    ++cap_puts;
    *cap = (struct swapz_ticket_cap){0};
    return 0;
}
'''
TEST = r'''
#define CHECK(x) do { if (!(x)) { fprintf(stderr, "registry failure line=%d\n", __LINE__); return 1; } } while (0)
static unsigned int interleave;
static void install_interleave(void)
{
    struct swapz_dm *ctx = observed_ctx;
    if (!ctx->original_route.registration_epoch)
        return;
    before_lock = NULL;
    if (interleave == 1U)
        ctx->failed = true;
    else if (interleave == 2U) {
        struct swapz_round089_route replacement = {0};
        /* Execute real route revoke and replacement before late install. */
        ctx->queue_lock = true;
        swapz_round089_revoke_route_locked(ctx);
        ctx->queue_lock = false;
        assert(swapz_round089_register_route(ctx->target, 1, 2, 4,
                                             &replacement) == 0);
    } else if (interleave == 3U)
        ctx->accepting = false;
}
static int test_bind(void)
{
    int table = 0;
    struct swapz_dm ctx = {.accepting = true};
    struct dm_target ti = {&ctx, &table, 0};
    struct swapz_ticket_broker broker = {.session = 1, .epoch = 2};
    u64 old_epoch;
    ctx.target = &ti;
    observed_ctx = &ctx;
    swapz_round089_route_sequence = 0;
    CHECK(swapz_round090_bind_capability(NULL, &broker, 1, 2, 3) == -EINVAL);
    broker.refuse = true;
    CHECK(swapz_round090_bind_capability(&ti, &broker, 1, 2, 3) == -ESTALE);
    CHECK(!ctx.original_route.registration_epoch && !broker.caps && !cap_gets);
    broker.refuse = false;
    interleave = 1U;
    before_lock = install_interleave;
    CHECK(swapz_round090_bind_capability(&ti, &broker, 1, 2, 3) == -ESTALE);
    CHECK(!ctx.original_route.registration_epoch && !ctx.original_cap.broker);
    CHECK(!broker.caps && cap_gets == 1U && cap_puts == 1U && !ctx.queue_lock);
    ctx.failed = false;
    interleave = 3U;
    before_lock = install_interleave;
    CHECK(swapz_round090_bind_capability(&ti, &broker, 1, 2, 3) == -ESTALE);
    CHECK(!ctx.original_route.registration_epoch && !broker.caps && cap_gets == cap_puts);
    ctx.accepting = true;
    interleave = 2U;
    before_lock = install_interleave;
    CHECK(swapz_round090_bind_capability(&ti, &broker, 1, 2, 3) == -ESTALE);
    CHECK(ctx.original_route.registration_epoch && ctx.original_route.target_epoch == 4U);
    CHECK(!ctx.original_cap.broker && !broker.caps && cap_gets == cap_puts);
    ctx.queue_lock = true;
    swapz_round089_revoke_route_locked(&ctx);
    ctx.queue_lock = false;
    CHECK(swapz_round090_bind_capability(&ti, &broker, 1, 2, 5) == 0);
    old_epoch = ctx.original_route.registration_epoch;
    CHECK(old_epoch && ctx.original_cap.broker == &broker && broker.caps == 1U);
    CHECK(swapz_round090_bind_capability(&ti, &broker, 1, 2, 5) == -EALREADY);
    CHECK(ctx.original_route.registration_epoch == old_epoch && broker.caps == 1U);
    ctx.queue_lock = true;
    swapz_round089_revoke_route_locked(&ctx);
    ctx.queue_lock = false;
    CHECK(swapz_ticket_broker_put(&ctx.original_cap) == 0);
    CHECK(!broker.caps && cap_gets == cap_puts && !ctx.queue_lock);
    puts("ROUND093_BIND_ROLLBACK_PASS host_cap_adapter_only AUTH=0");
    return 0;
}
int main(void)
{
    int table = 0;
    struct swapz_dm ctx = { .accepting = true };
    struct dm_target ti = { &ctx, &table, 0 };
    struct swapz_round089_route first = {0}, next = {0}, stale;
    ctx.target = &ti;
    CHECK(swapz_round089_register_route(NULL, 1, 2, 3, &first) == -EINVAL);
    CHECK(swapz_round089_register_route(&ti, 0, 2, 3, &first) == -EINVAL);
    CHECK(swapz_round089_register_route(&ti, 1, 0, 3, &first) == -EINVAL);
    CHECK(swapz_round089_register_route(&ti, 1, 2, 0, &first) == -EINVAL);
    ctx.accepting = false;
    CHECK(swapz_round089_register_route(&ti, 1, 2, 3, &first) == -ESHUTDOWN);
    ctx.accepting = true; ctx.failed = true;
    CHECK(swapz_round089_register_route(&ti, 1, 2, 3, &first) == -ESHUTDOWN);
    ctx.failed = false;
    contend = true;
    CHECK(swapz_round089_register_route(&ti, 1, 2, 3, &first) == -EAGAIN &&
          !first.registration_epoch && !ctx.original_route.registration_epoch);
    contend = false;
    CHECK(swapz_round089_register_route(&ti, 1, 2, 3, &first) == 0 &&
          first.registration_epoch == 2);
    CHECK(swapz_round089_register_route(&ti, 1, 2, 3, &next) == -EALREADY &&
          !next.registration_epoch);
    ctx.queue_lock = true;
    CHECK(swapz_round089_route_matches_locked(&ctx, &first));
    stale = first; stale.table_epoch++;
    CHECK(!swapz_round089_route_matches_locked(&ctx, &stale));
    stale = first; stale.target_epoch++;
    CHECK(!swapz_round089_route_matches_locked(&ctx, &stale));
    stale = first; stale.broker_session++;
    CHECK(!swapz_round089_route_matches_locked(&ctx, &stale));
    swapz_round089_revoke_route_locked(&ctx);
    CHECK(!swapz_round089_route_matches_locked(&ctx, &first));
    ctx.queue_lock = false;
    CHECK(swapz_round089_register_route(&ti, 1, 2, 3, &next) == 0 &&
          next.registration_epoch > first.registration_epoch);
    ctx.queue_lock = true;
    CHECK(!swapz_round089_route_matches_locked(&ctx, &first) &&
          swapz_round089_route_matches_locked(&ctx, &next));
    swapz_round089_revoke_route_locked(&ctx);
    ctx.queue_lock = false;
    swapz_round089_route_sequence = S64_MAX;
    CHECK(swapz_round089_register_route(&ti, 1, 2, 3, &next) == -EOVERFLOW &&
          !next.registration_epoch && !ctx.original_route.registration_epoch);
    CHECK(!ctx.queue_lock);
    puts("ROUND089_REGISTRY_PASS checks=18 host_adapters_only AUTH=0");
    return test_bind();
}
'''


def main():
    source = SOURCE.read_text()
    anchor = "list_add_tail(&entry->list, &ctx->incoming);"
    if source.count(anchor) != 1:
        raise SystemExit("legacy mutation anchor count changed: " + anchor)
    mapping = extract(source, "static int swapz_map(struct dm_target *ti, struct bio *bio)",
                      "static void swapz_drain(")
    assert mapping.index("swapz_round089_core_matches(ti, bio, candidate)") < mapping.index(
        "spin_lock_irqsave(&ctx->queue_lock, flags)")
    assert mapping.index("swapz_round088_try_claim_locked(ti, ctx, entry, candidate") < mapping.index(anchor)
    assert mapping.count(anchor) == 1
    for begin, end in (("static void swapz_fail_at(", "/* Keep unclassified"),
                       ("static void swapz_drain(", "static void swapz_resume(")):
        section = extract(source, begin, end)
        assert section.index("spin_lock_irqsave(&ctx->queue_lock, flags)") < section.index(
            "swapz_round089_revoke_route_locked(ctx);") < section.index(
            "spin_unlock_irqrestore(&ctx->queue_lock, flags)")
    record = extract(source, "struct swapz_round089_route {", "/* Globally non-reused")
    revoke = extract(source, "static void swapz_round089_revoke_route_locked(", "#endif")
    functions = extract(source, "static __maybe_unused int swapz_round089_register_route(",
                        "/* Original core validation runs")
    bind = extract(source, "static __maybe_unused int swapz_round090_bind_capability(",
                   "/* ROUND090_DESTINATION_CREDIT_BEGIN */")
    with tempfile.TemporaryDirectory(prefix="round089-route-") as directory:
        program = Path(directory) / "registry.c"
        executable = program.with_suffix("")
        rollback = ("if (swapz_round089_route_matches_locked(ctx, &route))\n"
                    "\t\t\t\tswapz_round089_revoke_route_locked(ctx);")
        assert bind.count(rollback) == 1
        variants = {
            "baseline": bind,
            "omit_rollback": bind.replace(rollback, "", 1),
            "revoke_newer_route": bind.replace(
                rollback, "swapz_round089_revoke_route_locked(ctx);", 1),
        }
        for compiler in ("gcc", "clang"):
            for name, variant in variants.items():
                program.write_text(ADAPTER + record + CONTEXT + revoke + functions + variant + TEST)
                subprocess.run([compiler, "-std=gnu11", "-O1", "-g", "-Wall", "-Wextra",
                                "-Wconversion", "-Wshadow", "-Werror", "-fsanitize=address,undefined",
                                "-fno-pie", "-no-pie", str(program), "-o", str(executable)],
                               check=True, timeout=30)
                result = subprocess.run([str(executable)], capture_output=True, text=True, timeout=10)
                if name == "baseline":
                    if result.returncode or result.stderr or "ROUND093_BIND_ROLLBACK_PASS" not in result.stdout:
                        raise RuntimeError(f"{compiler} binding baseline failed: {result.returncode}: {result.stderr[:500]}")
                    print(result.stdout, end="")
                else:
                    # Reject only the actual test assertion, never a compiler/sanitizer failure.
                    if (result.returncode != 1 or
                            not result.stderr.startswith("registry failure line=") or
                            len(result.stderr.splitlines()) != 1 or
                            "ROUND093_BIND_ROLLBACK_PASS" in result.stdout):
                        raise RuntimeError(f"{compiler} unexpected {name} result: {result.returncode}: {result.stderr[:500]}")
                    print(f"ROUND093_BIND_MUTANT_KILLED compiler={compiler} name={name}")
    print("ROUND089_CANONICAL_ENQUEUE_ANCHOR_PASS count=1")


if __name__ == "__main__":
    main()
