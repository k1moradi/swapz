#!/usr/bin/env python3
"""Extract actual target registry functions; host adapters are not kernel locks."""
from pathlib import Path
import hashlib
import os
import re
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "src/kernel/dm-target.c"
FROZEN_R100 = "78d5a7e5231669cd9c1213e3a2682e3b01dcd79d"
FROZEN_DM = "0f53224a43ef8aec58b2627904c5204e67a6a295"


def extract(source, begin, end):
    if source.count(begin) != 1:
        raise SystemExit("source extraction anchor drift: " + begin)
    tail = source.split(begin, 1)[1]
    if end not in tail:
        raise SystemExit("source extraction end missing: " + end)
    return begin + tail.split(end, 1)[0]


def read_source():
    """Use current product unless the dedicated R100 frozen lane is selected."""
    if os.environ.get("SWAPZ_R100_FROZEN_HOST") != "1":
        return SOURCE.read_text()
    data = subprocess.check_output(
        ["git", "show", FROZEN_R100 + ":src/kernel/dm-target.c"], cwd=ROOT)
    digest = hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()
    if digest != FROZEN_DM:
        raise RuntimeError("R100 frozen DM blob mismatch")
    print("R100_FROZEN_DM", FROZEN_R100, digest, flush=True)
    return data.decode("utf-8")


REVOKE_BEGIN = "static void swapz_round089_revoke_route_locked("
REVOKE_NEXT = "static void swapz_fail_at("


def extract_revoke(source):
    """Exact function bytes, including nested guards, excluding outer guard.

    The next declaration and outer guard must be unique and adjacent.
    Reject unbalanced conditional branches instead of guessing a C boundary.
    """
    if source.count(REVOKE_BEGIN) != 1 or source.count(REVOKE_NEXT) != 1:
        raise RuntimeError("revoke extraction ambiguous or missing anchor")
    start = source.index(REVOKE_BEGIN)
    end = source.index(REVOKE_NEXT)
    if end <= start:
        raise RuntimeError("revoke extraction reversed anchors")
    region = source[start:end]
    function, separator, trailing = region.rpartition("\n#endif\n")
    if not separator or trailing.strip() or not function.endswith("\n}"):
        raise RuntimeError("revoke extraction missing outer guard or closing brace")
    # Mask comments and literals for analysis only; return unchanged bytes.
    token = re.compile(r'''/\*[\s\S]*?\*/|//[^\n]*|"(?:\\.|[^"\\\n])*"|'(?:\\.|[^'\\\n])*'|/\*|["']''')
    def mask(match):
        value = match.group()
        if value in ("/*", '"', "'"):
            raise RuntimeError("revoke extraction unterminated comment/literal")
        return "".join("\n" if char == "\n" else " " for char in value)
    lexical = token.sub(mask, function)
    signature, opening, body = lexical.partition("\n{\n")
    if not opening or not re.fullmatch(
            r"static void swapz_round089_revoke_route_locked\([^\n{};]+\)", signature):
        raise RuntimeError("revoke extraction malformed signature")
    depth = 1
    guards = []
    lines = body.splitlines()
    for index, line in enumerate(lines):
        directive = re.match(r"^\s*#\s*(\w+)\b(.*)$", line)
        if directive:
            name, argument = directive.groups()
            if line.endswith("\\"):
                raise RuntimeError("revoke extraction unsupported continued directive")
            if name in ("if", "ifdef", "ifndef"):
                if not argument.strip():
                    raise RuntimeError("revoke extraction missing guard condition")
                guards.append((depth, False))
            elif name in ("elif", "else", "endif"):
                if not guards or depth != guards[-1][0]:
                    raise RuntimeError("revoke extraction unbalanced guard branch")
                if name == "endif":
                    if argument.strip():
                        raise RuntimeError("revoke extraction malformed endif")
                    guards.pop()
                else:
                    if guards[-1][1] or (name == "else" and argument.strip()) or (
                            name == "elif" and not argument.strip()):
                        raise RuntimeError("revoke extraction malformed alternate guard")
                    guards[-1] = (depth, name == "else")
            else:
                raise RuntimeError("revoke extraction unsupported directive")
            continue
        if line.lstrip().startswith("#"):
            raise RuntimeError("revoke extraction malformed directive")
        for char in line:
            if char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth < 0 or (depth == 0 and
                        (guards or index != len(lines) - 1 or line.strip() != "}")):
                    raise RuntimeError("revoke extraction premature function close")
    if guards or depth:
        raise RuntimeError("revoke extraction unbalanced function/guards")
    return function + "\n"


def check_revoke_extraction():
    """Regression for first-endif truncation and malformed seams."""
    signature = REVOKE_BEGIN + "struct swapz_dm *ctx)\n{\n"
    nested = (
        "\t/* #endif and } are comment text, not boundaries. */\n"
        "#if defined(OUTER)\n#if INNER\n\tctx->route = (struct route){};\n"
        "#elif OTHER\n\tctx->route = (struct route){1};\n"
        "#else\n\tctx->route = (struct route){2};\n#endif\n"
        "#endif\n\t(void)ctx;\n}\n")
    suffix = "#endif\n\n" + REVOKE_NEXT + "void);\n"
    genuine = signature + nested
    if extract_revoke(genuine + suffix) != genuine:
        raise RuntimeError("R100 extraction changed genuine nested body")
    malformed = {
        "missing_outer": genuine + REVOKE_NEXT + "void);\n",
        "missing_inner": (genuine + suffix).replace("#endif\n#endif\n", "#endif\n", 1),
        "stray_else": (genuine + suffix).replace("#if defined(OUTER)", "#else", 1),
        "double_else": (genuine + suffix).replace("#else\n", "#else\n#else\n", 1),
        "branch_brace": (genuine + suffix).replace("struct route){};", "struct route){;", 1),
        "premature_close": (genuine + suffix).replace("\t(void)ctx;", "}\n\t(void)ctx;", 1),
        "missing_close": (genuine + suffix).replace("\n}\n#endif", "\n#endif", 1),
        "duplicate_start": genuine + genuine + suffix,
        "duplicate_next": genuine + suffix + REVOKE_NEXT + "void);\n",
        "unterminated_comment": (genuine + suffix).replace(
            "/* #endif and } are comment text, not boundaries. */", "/* unclosed"),
    }
    for name, candidate in malformed.items():
        try:
            extract_revoke(candidate)
        except RuntimeError:
            continue
        raise RuntimeError("R100 malformed extraction accepted: " + name)
    print("R100_EXTRACTION_BOUNDARY_PASS positive=1 malformed=10", flush=True)


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
/* Host value-layout adapter for the actual guarded scope revoke only. */
struct block_device { unsigned int unused; };
struct swapz_mm_trial_scope {
    struct block_device *bdev;
    struct swapz_ticket_broker *broker;
    u64 identity, session, table_epoch, target_epoch, area_epoch;
    u64 first_sector, sector_count;
    uint32_t swap_type;
};
struct swapz_dm {
    struct dm_target *target;
    bool queue_lock, accepting, failed;
    struct swapz_round089_route original_route;
    struct swapz_ticket_cap original_cap;
    struct swapz_mm_trial_scope original_scope;
    u64 original_scope_used_session;
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
    /* Exercise the real nested R098 revoke branch, not just parse it. */
#if defined(SWAPZ_ROUND098_SCOPED_TARGET_TEST)
    ctx.original_scope = (struct swapz_mm_trial_scope){
        .bdev = &((struct block_device){0}), .broker = &((struct swapz_ticket_broker){0}),
        .identity = 7, .session = 1, .table_epoch = 2, .target_epoch = 3,
        .area_epoch = 4, .first_sector = 8, .sector_count = 16, .swap_type = 2,
    };
    ctx.original_scope_used_session = 1;
#endif
    swapz_round089_revoke_route_locked(&ctx);
    CHECK(!swapz_round089_route_matches_locked(&ctx, &first));
#if defined(SWAPZ_ROUND098_SCOPED_TARGET_TEST)
    CHECK(!ctx.original_scope.bdev && !ctx.original_scope.broker &&
          !ctx.original_scope.identity && !ctx.original_scope.session &&
          !ctx.original_scope.table_epoch && !ctx.original_scope.target_epoch &&
          !ctx.original_scope.area_epoch && !ctx.original_scope.first_sector &&
          !ctx.original_scope.sector_count && !ctx.original_scope.swap_type);
    CHECK(ctx.original_scope_used_session == 1);
    puts("R100_SCOPED_REVOKE_PASS checks=2");
#endif
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
    source = read_source()
    check_revoke_extraction()
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
    revoke = extract_revoke(source)
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
                                "-fno-sanitize-recover=all", "-fno-pie", "-no-pie",
                                *(["-DSWAPZ_ROUND098_SCOPED_TARGET_TEST"] if
                                  os.environ.get("SWAPZ_R100_FROZEN_HOST") == "1" else []),
                                str(program), "-o", str(executable)],
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
