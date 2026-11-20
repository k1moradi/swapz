#!/usr/bin/env python3
"""Round049: actual DM target-owned accepted BIO/ACK/GC/dtr NO_AUTH audit.

Uses exact pinned ORIGINAL Linux DM source and real product C. All hostile
controls mutate genuine function bodies; none supply a source slot reference,
external table lease, separately tagged lower I/O, or positive authorization.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import runpy

PREVIOUS = runpy.run_path(
    str(Path(__file__).with_name("round048-dm-live-table-source-audit.py")),
    run_name="round048_source_library",
)
LOAD_SOURCES = PREVIOUS["load_sources"]
CHECK_PRIOR = PREVIOUS["validate_sources"]
EXACT_FUNCTION = PREVIOUS["exact_function"]
ORIGINAL_KERNEL = PREVIOUS["ORIGINAL_LINUX_COMMIT"]

# Each owner/signature is an actual function in the original pinned
# drivers/md/dm.c or the real production src/kernel/dm-target.c.
FUNCTIONS = {
    "core_clone_map": ("dm", "static void __map_bio("),
    "core_clone_ack": ("dm", "static void clone_endio("),
    "core_unbind": ("dm", "static struct dm_table *__unbind("),
    "accepted_map": ("product", "static int swapz_map(struct dm_target *ti, struct bio *bio)"),
    "complete": ("product", "static void swapz_complete("),
    "offloaded_ack": ("product", "static void swapz_completion_work("),
    "handoff_ack": ("product", "static bool swapz_try_completion_handoff("),
    "direct_ack": ("product", "static void swapz_deliver_bio_list("),
    "end_io": ("product", "static int swapz_end_io("),
    "lower_write_done": ("product", "static void swapz_async_lower_write_done("),
    "ordered_worker": ("product", "static void swapz_worker_pass("),
    "drain": ("product", "static void swapz_drain("),
    "dtr": ("product", "static void swapz_dtr("),
    "gc_relocation": ("product", "static int swapz_gc_relocate_one("),
    "negative_table_witness": (
        "product", "static __used noinline int swapz_round046_dm_lifetime_refuse("),
}

# Each required token MUST occur exactly once inside that function. No
# simulated ACK counter is a replacement for the actual DM clone completion.
REQUIRED = {
    "core_clone_map": (
        "clone->bi_end_io = clone_endio;",
        "r = ti->type->map(ti, clone);",
        "case DM_MAPIO_SUBMITTED:",
        "/* target has assumed ownership of this io */",
    ),
    "core_clone_ack": (
        "case DM_ENDIO_INCOMPLETE:",
        "free_tio(bio);",
        "dm_io_dec_pending(io, error);",
    ),
    "core_unbind": (
        "RCU_INIT_POINTER(md->map, NULL);",
        "dm_sync_table(md);",
    ),
    "accepted_map": (
        "if (!READ_ONCE(ctx->accepting))",
        "sector % SWAPZ_SECTORS || count != SWAPZ_SECTORS",
        "entry = dm_per_bio_data(bio, sizeof(*entry));",
        "if (!ctx->accepting)",
        "list_add_tail(&entry->list, &ctx->incoming);",
        "return DM_MAPIO_SUBMITTED;",
    ),
    "complete": (
        "if (!error && ctx && smp_load_acquire(&ctx->failed))",
        "bio->bi_status = errno_to_blk_status(error);",
        "swapz_release_prepared(bio);",
        "bio_endio(bio);",
    ),
    "offloaded_ack": (
        "while ((bio = bio_list_pop(&ctx->completion_bios))) {",
        "swapz_complete(bio, 0);",
        "atomic_set_release(&ctx->completion_active, 0);",
    ),
    "handoff_ack": (
        "if (ctx->accepting && !READ_ONCE(ctx->failed) &&",
        "!atomic_cmpxchg(&ctx->completion_active, 0, 1)",
        "ctx->completion_bios = ctx->deferred_upper_completions;",
        "bio_list_init(&ctx->deferred_upper_completions);",
        "queue_work(ctx->preparation_workqueue, &ctx->completion_work);",
    ),
    "direct_ack": (
        "while ((bio = bio_list_pop(bios))) {",
        "swapz_complete(bio, 0);",
    ),
    "end_io": (
        "if (!*error && smp_load_acquire(&ctx->failed))",
        "*error = errno_to_blk_status(failure ? failure : -EIO);",
    ),
    "lower_write_done": (
        "struct swapz_dm *ctx = inflight->ctx;",
        "WRITE_ONCE(inflight->lower_error, lower_error);",
        "spin_lock_irqsave(&ctx->queue_lock, flags);",
        "complete(&inflight->lower_done);",
        "mod_delayed_work(ctx->workqueue, &ctx->worker, 0);",
        "spin_unlock_irqrestore(&ctx->queue_lock, flags);",
    ),
    "ordered_worker": (
        "if (!head || !completion_done(&head->lower_done))",
        "inflight_error = swapz_finalize_inflight_write(ctx, false);",
        "list_splice_init(&ctx->incoming, &local);",
    ),
    "drain": (
        "WRITE_ONCE(ctx->accepting, false);",
        "hrtimer_cancel(&ctx->retention_timer);",
        "wait_for_completion(&head->lower_done);",
        "drain_workqueue(ctx->workqueue);",
        "atomic_read(&ctx->completion_active)",
        "!bio_list_empty(&ctx->completion_bios)",
    ),
    "dtr": (
        "swapz_drain(ti);",
        "swapz_free(ctx);",
        "ti->private = NULL;",
    ),
    "gc_relocation": (
        "snapshot = ctx->maps[logical];",
        "swapz_gc_move_raw(ctx, logical, &snapshot);",
        "error = swapz_engine_read_page(&ctx->engine, logical,",
        "ctx->gc_pending[ctx->gc_count++] =",
        ".encoding = swapz_map_encoding(&snapshot),",
    ),
    "negative_table_witness": (
        "target->private != ctx",
        "ctx->target != target",
        "target_relative_sector = upper_bio->bi_iter.bi_sector",
        "bio_sectors(upper_bio) != SWAPZ_SECTORS",
        "submitted->table_epoch != observed->table_epoch",
        "submitted->map_generation != observed->map_generation",
        "submitted->gc_destination != observed->gc_destination",
        "submitted->original_bdev_cookie != observed->original_bdev_cookie",
        "submitted->original_physical_sector != observed->original_physical_sector",
    ),
}

# Every actual real-source mutant changes one scoped function, never an
# unrelated token in the giant full product translation unit. The initial
# eight cover upper ACK exactly-once and close-admission first.
MUTATIONS = (
    ("core_clone_map", "r = ti->type->map(ti, clone);",
     "r = DM_MAPIO_SUBMITTED;"),
    ("core_clone_ack", "dm_io_dec_pending(io, error);",
     "/* pending original upper I/O never completed */"),
    ("core_unbind", "dm_sync_table(md);",
     "/* no SRCU barrier before table teardown */"),
    ("accepted_map", "if (!READ_ONCE(ctx->accepting))",
     "if (false)"),
    ("accepted_map", "sector % SWAPZ_SECTORS || count != SWAPZ_SECTORS",
     "sector % SWAPZ_SECTORS || count != 0"),
    ("accepted_map", "list_add_tail(&entry->list, &ctx->incoming);",
     "/* accepted BIO loses its only queue owner */"),
    ("complete", "if (!error && ctx && smp_load_acquire(&ctx->failed))",
     "if (false)"),
    ("complete", "bio_endio(bio);",
     "bio_endio(bio); bio_endio(bio);"),
    ("offloaded_ack", "swapz_complete(bio, 0);",
     "swapz_complete(bio, 0); swapz_complete(bio, 0);"),
    ("offloaded_ack", "atomic_set_release(&ctx->completion_active, 0);",
     "/* completion lane never released */"),
    ("handoff_ack", "!atomic_cmpxchg(&ctx->completion_active, 0, 1)",
     "true /* duplicate completion handoff admitted */"),
    ("handoff_ack", "bio_list_init(&ctx->deferred_upper_completions);",
     "/* original list also retains the same ACK BIOs */"),
    ("direct_ack", "swapz_complete(bio, 0);",
     "swapz_complete(bio, 0); swapz_complete(bio, 0);"),
    ("end_io", "if (!*error && smp_load_acquire(&ctx->failed))",
     "if (false)"),
    ("lower_write_done", "WRITE_ONCE(inflight->lower_error, lower_error);",
     "/* stale lower completion never records real result */"),
    ("lower_write_done", "complete(&inflight->lower_done);",
     "/* owner and destructor never observe lower completion */"),
    ("lower_write_done", "mod_delayed_work(ctx->workqueue, &ctx->worker, 0);",
     "/* owner never woken after lower completion */"),
    ("ordered_worker", "if (!head || !completion_done(&head->lower_done))",
     "if (!head)"),
    ("drain", "WRITE_ONCE(ctx->accepting, false);",
     "WRITE_ONCE(ctx->accepting, true);"),
    ("drain", "wait_for_completion(&head->lower_done);",
     "/* pending lower callback not drained */"),
    ("drain", "drain_workqueue(ctx->workqueue);",
     "/* chained accepted work can outlive target teardown */"),
    ("dtr", "swapz_drain(ti);",
     "/* context freed with outstanding async clone owners */"),
    ("gc_relocation", "snapshot = ctx->maps[logical];",
     "/* stale copied extent is not a current authority snapshot */"),
    ("gc_relocation", ".encoding = swapz_map_encoding(&snapshot),",
     ".encoding = 0, /* stale encoding after GC */"),
    ("negative_table_witness",
     "submitted->map_generation != observed->map_generation",
     "false /* stale extent ABA incorrectly accepted */"),
    ("negative_table_witness",
     "submitted->original_physical_sector != observed->original_physical_sector",
     "false /* source physical LBA conflated with target-relative sectors */"),
)

# Explicitly test dynamic order constraints: the source alone can show
# ordering, not prove externally retained table/slot ownership.
ORDERED = {
    "core_clone_map": (
        "clone->bi_end_io = clone_endio;",
        "r = ti->type->map(ti, clone);",
        "case DM_MAPIO_SUBMITTED:",
    ),
    "core_clone_ack": (
        "free_tio(bio);",
        "dm_io_dec_pending(io, error);",
    ),
    "core_unbind": (
        "RCU_INIT_POINTER(md->map, NULL);",
        "dm_sync_table(md);",
    ),
    "accepted_map": (
        "if (!READ_ONCE(ctx->accepting))",
        "entry = dm_per_bio_data(bio, sizeof(*entry));",
        "if (!ctx->accepting)",
        "list_add_tail(&entry->list, &ctx->incoming);",
        "return DM_MAPIO_SUBMITTED;",
    ),
    "complete": (
        "if (!error && ctx && smp_load_acquire(&ctx->failed))",
        "bio->bi_status = errno_to_blk_status(error);",
        "bio_endio(bio);",
    ),
    "offloaded_ack": (
        "while ((bio = bio_list_pop(&ctx->completion_bios))) {",
        "swapz_complete(bio, 0);",
        "atomic_set_release(&ctx->completion_active, 0);",
    ),
    "handoff_ack": (
        "!atomic_cmpxchg(&ctx->completion_active, 0, 1)",
        "ctx->completion_bios = ctx->deferred_upper_completions;",
        "bio_list_init(&ctx->deferred_upper_completions);",
        "queue_work(ctx->preparation_workqueue, &ctx->completion_work);",
    ),
    "lower_write_done": (
        "WRITE_ONCE(inflight->lower_error, lower_error);",
        "spin_lock_irqsave(&ctx->queue_lock, flags);",
        "complete(&inflight->lower_done);",
        "mod_delayed_work(ctx->workqueue, &ctx->worker, 0);",
        "spin_unlock_irqrestore(&ctx->queue_lock, flags);",
    ),
    "ordered_worker": (
        "if (!head || !completion_done(&head->lower_done))",
        "inflight_error = swapz_finalize_inflight_write(ctx, false);",
        "list_splice_init(&ctx->incoming, &local);",
    ),
    "drain": (
        "WRITE_ONCE(ctx->accepting, false);",
        "wait_for_completion(&head->lower_done);",
        "drain_workqueue(ctx->workqueue);",
        "atomic_read(&ctx->completion_active)",
    ),
    "dtr": ("swapz_drain(ti);", "swapz_free(ctx);", "ti->private = NULL;"),
    "gc_relocation": (
        "snapshot = ctx->maps[logical];",
        "error = swapz_engine_read_page(&ctx->engine, logical,",
        "ctx->gc_pending[ctx->gc_count++] =",
    ),
}


def fail(message: str) -> None:
    raise AssertionError("Round049 target-owned in-band NO_AUTH: " + message)


def validate(sources: dict[str, str]) -> None:
    CHECK_PRIOR(sources)
    sections = {}
    for label, (owner, signature) in FUNCTIONS.items():
        function = EXACT_FUNCTION(sources[owner], signature)
        sections[label] = function
        for required in REQUIRED[label]:
            if function.count(required) != 1:
                fail("missing/duplicated source-local real C " + label +
                     " anchor " + required)
    for label, tokens in ORDERED.items():
        function = sections[label]
        positions = [function.index(token) for token in tokens]
        if positions != sorted(positions) or len(positions) != len(set(positions)):
            fail("original C owner/release/ACK order changed: " + label)

    # bio_endio(bio) is the only actual target clone completion; none of
    # the separate list workers may race to complete that same clone.
    if sections["complete"].count("bio_endio(bio);") != 1:
        fail("target clone BIO was ended other than exactly once")
    for label in ("offloaded_ack", "handoff_ack", "direct_ack"):
        if "bio_endio(" in sections[label].replace(
                "bio_endio() is IRQ-safe.", ""):
            fail("secondary completion lane bypassed sole owner " + label)

    # These are *negative invariants* for the future compressed staging.
    # The real external original Linux swap-slot counted ref and independent
    # current table/GC/dtr transfer do not exist in this target.
    product = sources["product"]
    if "SOURCE_MAPPED_AUTHENTICATED 1" in product:
        fail("unowned source mapping was enabled")
    witness = sections["negative_table_witness"]
    if "return 0;" in witness:
        fail("synthetic scalar witness fabricated success")
    if witness.count("return -EOPNOTSUPP;") < 1:
        fail("synthetic source-table witness no longer fail-closed")


def hostile(sources: dict[str, str]) -> None:
    original = dict(sources)
    if len(MUTATIONS) != 26:
        fail("inherited 26 target-owned hostile controls truncated")
    seen = set()
    for label, before, after in MUTATIONS:
        identity = (label, before, after)
        if identity in seen:
            fail("duplicate hostile source mutation control")
        seen.add(identity)
        owner, signature = FUNCTIONS[label]
        real_function = EXACT_FUNCTION(original[owner], signature)
        if real_function.count(before) != 1:
            fail("original hostile anchor missing or nonunique in " + label)
        mutated_function = real_function.replace(before, after, 1)
        if mutated_function == real_function:
            fail("no-op hostile source control " + label)
        if original[owner].count(real_function) != 1:
            fail("real original function span is not unique " + label)
        mutant = dict(original)
        mutant[owner] = original[owner].replace(
            real_function, mutated_function, 1)
        if mutant[owner] == original[owner]:
            fail("hostile changed no actual original C bytes " + label)
        for other_owner in original.keys() - {owner}:
            if mutant[other_owner] != original[other_owner]:
                fail("source-hostile mutant escaped its original file")
        try:
            validate(mutant)
        except AssertionError as error:
            if not str(error).startswith(("Round049 ", "Round048 ")):
                raise
        else:
            fail("mutated actual C incorrectly permitted: " + label)
    print("ROUND049_DM_TARGET_OWNED_26_ACTUAL_SOURCE_HOSTILES_REJECTED_PASS")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--kernel-root", type=Path, required=True)
    options = parser.parse_args()
    sources = LOAD_SOURCES(options.kernel_root)
    validate(sources)
    hostile(sources)
    print("ROUND049_DM_TARGET_OWNED_ORIGINAL_CLONE_ACK_GC_DTR_NOAUTH_PASS")
    print("ROUND049_PINNED_ORIGINAL_LINUX_" + ORIGINAL_KERNEL)
    print("ROUND049_REAL_SOURCE_TO_CURRENT_DM_TABLE_OWNER_ACQUIRED=0")
    print("ROUND049_EXTERNAL_STORED_LZ4_LOWER_TRANSFER_DISABLED")


if __name__ == "__main__":
    main()
