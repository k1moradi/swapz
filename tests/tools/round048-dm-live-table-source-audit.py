#!/usr/bin/env python3
"""Round048: source-exact, fail-only original DM table/GC/dtr lifetime audit.

This is not a DM table pin and never authorizes compressed source-to-target I/O.
Read genuine pristine pinned Linux DM C, not copied mock implementations.
"""
from __future__ import annotations

import argparse
import hashlib
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[2]
PRODUCT_PATH = ROOT / "src/kernel/dm-target.c"
ORIGINAL_LINUX_COMMIT = "c339f4010dea8b0d754f84ace70cd1b089878ef8"
PINNED_KERNEL_BLOBS = {
    "drivers/md/dm.c": "1881d86111fb2e655893ad898cf21b88f0e4e7f3",
    "drivers/md/dm-table.c": "a483f49dd4ce6383ef66464707865187aa4cf51c",
    "include/linux/device-mapper.h": "cd4faaf5d4275c038d06ccef4da3d77430154388",
}
EXPECTED = "ROUND048_ORIGINAL_DM_LIVE_TABLE_GC_DTR_NO_AUTH_SOURCE_PASS"
HOSTILE_EXPECTED = "ROUND048_ORIGINAL_DM_TABLE_GC_DTR_18_HOSTILE_SOURCE_MUTANTS_REJECTED_PASS"

# Deliberately match the real function declarations in the pinned original
# kernel and production target, including their specific return types.
FUNCTIONS = {
    "table_acquire": ("dm", "struct dm_table *dm_get_live_table("),
    "table_release": ("dm", "void dm_put_live_table("),
    "table_barrier": ("dm", "void dm_sync_table("),
    "table_bind": ("dm", "static struct dm_table *__bind("),
    "table_unbind": ("dm", "static struct dm_table *__unbind("),
    "core_map": ("dm", "static void __map_bio("),
    "table_destroy": ("table", "void dm_table_destroy("),
    "lower_callback": ("product", "static void swapz_async_lower_write_done("),
    "target_drain": ("product", "static void swapz_drain("),
    "target_destruct": ("product", "static void swapz_dtr("),
    "target_map": ("product", "static int swapz_map(struct dm_target *ti, struct bio *bio)"),
    "gc_move": ("product", "static int swapz_gc_relocate_one("),
    "negative_observer": ("product", "static __used noinline int swapz_round046_dm_lifetime_refuse("),
}

# Source-derived obligations, NOT a synthetic successful lease. All must
# remain in the actual function (not merely anywhere in the C translation
# unit) so a renamed/removed or unrelated copied function cannot fake PASS.
REQUIREMENTS = {
    "table_acquire": (
        "*srcu_idx = srcu_read_lock(&md->io_barrier);",
        "return srcu_dereference(md->map, &md->io_barrier);",
    ),
    "table_release": ("srcu_read_unlock(&md->io_barrier, srcu_idx);",),
    "table_barrier": (
        "synchronize_srcu(&md->io_barrier);",
        "synchronize_rcu_expedited();",
    ),
    "table_bind": (
        "if (old_map)\n\t\tdm_sync_table(md);",
        "old_map = rcu_dereference_protected(md->map, lockdep_is_held(&md->suspend_lock));",
    ),
    "table_unbind": (
        "RCU_INIT_POINTER(md->map, NULL);",
        "dm_sync_table(md);",
    ),
    "core_map": (
        "struct dm_target *ti = tio->ti;",
        "r = ti->type->map(ti, clone);",
        "case DM_MAPIO_SUBMITTED:",
        "/* target has assumed ownership of this io */",
    ),
    "table_destroy": (
        "if (ti->type->dtr)",
        "ti->type->dtr(ti);",
        "kfree(t);",
    ),
    "lower_callback": (
        "struct swapz_dm *ctx = inflight->ctx;",
        "WRITE_ONCE(inflight->lower_error, lower_error);",
        "spin_lock_irqsave(&ctx->queue_lock, flags);",
        "complete(&inflight->lower_done);",
        "spin_unlock_irqrestore(&ctx->queue_lock, flags);",
    ),
    "target_drain": (
        "WRITE_ONCE(ctx->accepting, false);",
        "hrtimer_cancel(&ctx->retention_timer);",
        "wait_for_completion(&head->lower_done);",
        "drain_workqueue(ctx->workqueue);",
        "atomic_read(&ctx->completion_active)",
    ),
    "target_destruct": (
        "swapz_drain(ti);",
        "swapz_free(ctx);",
        "ti->private = NULL;",
    ),
    "target_map": (
        "struct swapz_dm *ctx = ti->private;",
        "entry = dm_per_bio_data(bio, sizeof(*entry));",
        "list_add_tail(&entry->list, &ctx->incoming);",
        "return DM_MAPIO_SUBMITTED;",
    ),
    "gc_move": (
        "snapshot = ctx->maps[logical];",
        "error = swapz_engine_read_page(&ctx->engine, logical,",
        "return swapz_gc_flush(ctx);",
    ),
    "negative_observer": (
        "target->private != ctx",
        "ctx->target != target",
        "target_relative_sector = upper_bio->bi_iter.bi_sector",
        "bio_sectors(upper_bio) != SWAPZ_SECTORS",
        "submitted->target_identity != (unsigned long)target",
        "submitted->table_epoch != observed->table_epoch",
        "submitted->map_generation != observed->map_generation",
        "submitted->extent_start_block != observed->extent_start_block",
        "submitted->gc_destination != observed->gc_destination",
        "submitted->original_bdev_cookie != observed->original_bdev_cookie",
        "submitted->original_physical_sector != observed->original_physical_sector",
        "return -EOPNOTSUPP;\n}",
    ),
}

# Every mutation changes the real pinned C source once, within the specified
# function. No no-op or mutation of an unrelated helper may count.
MUTATIONS = (
    ("table_acquire", "*srcu_idx = srcu_read_lock(&md->io_barrier);",
     "*srcu_idx = 0;"),
    ("table_release", "srcu_read_unlock(&md->io_barrier, srcu_idx);",
     "/* missing SRCU release */"),
    ("table_barrier", "synchronize_srcu(&md->io_barrier);",
     "/* missing table SRCU barrier */"),
    ("table_bind", "if (old_map)\n\t\tdm_sync_table(md);",
     "if (old_map)\n\t\t/* missing old-table barrier */;"),
    ("table_unbind", "RCU_INIT_POINTER(md->map, NULL);",
     "/* old table remains visible */"),
    ("core_map", "r = ti->type->map(ti, clone);",
     "r = DM_MAPIO_SUBMITTED;"),
    ("table_destroy", "ti->type->dtr(ti);",
     "/* no target destructor */"),
    ("lower_callback", "struct swapz_dm *ctx = inflight->ctx;",
     "struct swapz_dm *ctx = NULL;"),
    ("lower_callback", "complete(&inflight->lower_done);",
     "/* lower callback never wakes owner */"),
    ("target_drain", "WRITE_ONCE(ctx->accepting, false);",
     "WRITE_ONCE(ctx->accepting, true);"),
    ("target_drain", "wait_for_completion(&head->lower_done);",
     "/* forgot outstanding async lower write */"),
    ("target_destruct", "swapz_free(ctx);",
     "/* leaked or stale target context */"),
    ("target_map", "return DM_MAPIO_SUBMITTED;",
     "return DM_MAPIO_KILL;"),
    ("gc_move", "snapshot = ctx->maps[logical];",
     "memset(&snapshot, 0, sizeof(snapshot));"),
    ("negative_observer", "submitted->table_epoch != observed->table_epoch",
     "false /* skipped stale table epoch */"),
    ("negative_observer", "submitted->map_generation != observed->map_generation",
     "false /* skipped stale map generation */"),
    ("negative_observer", "submitted->gc_destination != observed->gc_destination",
     "false /* skipped GC relocation */"),
    ("negative_observer", "submitted->original_bdev_cookie != observed->original_bdev_cookie",
     "false /* ignored original source bdev */"),
)


def fail(message: str) -> None:
    raise AssertionError("Round048 current DM NO_AUTH source: " + message)


def original_git_blob_id(contents: bytes) -> str:
    # Git's actual immutable blob algorithm, not a filename or pasted SHA.
    return hashlib.sha1(
        b"blob " + str(len(contents)).encode("ascii") + b"\x00" + contents
    ).hexdigest()


def load_sources(kernel_root: Path) -> dict[str, str]:
    source_files = {"product": PRODUCT_PATH.read_text(encoding="utf-8")}
    for name, git_blob in PINNED_KERNEL_BLOBS.items():
        raw = (kernel_root / name).read_bytes()
        if original_git_blob_id(raw) != git_blob:
            fail("pristine pinned Linux Git blob mismatch: " + name)
        source_files[
            "dm" if name == "drivers/md/dm.c" else
            "table" if name == "drivers/md/dm-table.c" else "header"
        ] = raw.decode("utf-8")
    return source_files


def exact_function(source: str, signature: str) -> str:
    if source.count(signature) != 1:
        fail("real function signature is not unique: " + signature)
    start = source.index(signature)
    opened = source.find("{", start + len(signature))
    if opened < 0:
        fail("real C function body missing: " + signature)
    # Source has already been authenticated against real pinned Git blob.
    # The named function boundaries are independently tested by each mutant.
    depth = 0
    for position in range(opened, len(source)):
        if source[position] == "{":
            depth += 1
        elif source[position] == "}":
            depth -= 1
            if depth == 0:
                return source[start:position + 1]
    fail("real C function lacks balanced body: " + signature)


def validate_sources(sources: dict[str, str]) -> None:
    sections = {}
    for name, (owner, signature) in FUNCTIONS.items():
        region = exact_function(sources[owner], signature)
        sections[name] = region
        for mandatory in REQUIREMENTS[name]:
            if region.count(mandatory) != 1:
                fail(name + " lost actual original lifetime anchor: " + mandatory)

    # These SRCU reader helpers really exist in Linux DM core and the
    # header, but *neither* is EXPORT_SYMBOL() in this immutable kernel.
    # A visible C declaration is NOT an available, transferable module
    # reference. Do not silently assume an external swapz GPL module can
    # call it; dm_table_get_md export is not a table owner by itself.
    for helper in ("dm_get_live_table", "dm_put_live_table", "dm_sync_table"):
        if sources["header"].count(helper + "(") != 1:
            fail("missing original kernel public declaration " + helper)
        export = re.compile(
            r"EXPORT_SYMBOL(?:_GPL|_NS_GPL|_NS)?\s*\(\s*" +
            re.escape(helper) + r"\s*\)")
        if export.search(sources["dm"] + "\n" + sources["table"]):
            fail("unexpected exportable table reader/release API: " + helper)

    # The original Linux core owns the immediate ->map clone and records
    # an asynchronous DM_MAPIO_SUBMITTED BIO; that is not a new external
    # source-owned dm_table ref for separate zswap compressed bytes.
    callback = sections["lower_callback"]
    if not (callback.index("WRITE_ONCE(inflight->lower_error, lower_error);") <
            callback.index("spin_lock_irqsave(&ctx->queue_lock, flags);") <
            callback.index("complete(&inflight->lower_done);") <
            callback.index("spin_unlock_irqrestore(&ctx->queue_lock, flags);")):
        fail("async completion was not published under original queue lock")
    drain = sections["target_drain"]
    if not (drain.index("WRITE_ONCE(ctx->accepting, false);") <
            drain.index("wait_for_completion(&head->lower_done);") <
            drain.index("drain_workqueue(ctx->workqueue);")):
        fail("original drain closes admission after asynchronous wait")
    destructor = sections["target_destruct"]
    if not (destructor.index("swapz_drain(ti);") <
            destructor.index("swapz_free(ctx);") <
            destructor.index("ti->private = NULL;")):
        fail("target/ctx freed before draining prior accepted BIO")
    unbind = sections["table_unbind"]
    if not (unbind.index("RCU_INIT_POINTER(md->map, NULL);") <
            unbind.index("dm_sync_table(md);")):
        fail("table unbound after SRCU reader barrier")

    begin = "/* ROUND046_DM_LIFETIME_HELPER_EXACT_START */"
    end = "/* ROUND046_DM_LIFETIME_HELPER_EXACT_END */"
    product = sources["product"]
    if product.count(begin) != 1 or product.count(end) != 1:
        fail("actual Round046 source-negative guard markers missing")
    guarded = product.split(begin, 1)[1].split(end, 1)[0]
    if sections["negative_observer"] not in guarded:
        fail("Round046 negative helper is no longer inside default-off guard")
    if "#define SWAPZ_ROUND046_SOURCE_MAPPED_AUTHENTICATED 0U" not in guarded:
        fail("synthetic reports were given source authority")
    if "return 0;" in guarded:
        fail("source-negative observer invented positive lease")
    if "SOURCE_MAPPED_AUTHENTICATED 1" in product:
        fail("positive source-mapped authority introduced")


def run_hostile_sources(sources: dict[str, str]) -> None:
    if len(MUTATIONS) != 18:
        fail("missing original 18 hostile control count")
    original = dict(sources)
    count = 0
    for name, before, after in MUTATIONS:
        owner, signature = FUNCTIONS[name]
        region = exact_function(original[owner], signature)
        if region.count(before) != 1:
            fail("nonunique or absent original hostile anchor: " + name)
        altered = region.replace(before, after, 1)
        if altered == region:
            fail("no-op hostile C source mutation: " + name)
        if original[owner].count(region) != 1:
            fail("original function region not unique: " + name)
        mutant = dict(original)
        mutant[owner] = original[owner].replace(region, altered, 1)
        if mutant[owner] == original[owner]:
            fail("whole real C file unchanged: " + name)
        for other_owner in original.keys() - {owner}:
            if mutant[other_owner] != original[other_owner]:
                fail("hostile mutation spilled into other source owner")
        try:
            validate_sources(mutant)
        except AssertionError as error:
            if "Round048" not in str(error):
                raise
        else:
            fail("hostile actual C source mutant incorrectly accepted: " + name)
        count += 1

    # A fabricated exported table reader must also fail even though the
    # pristine original functions/markers remain otherwise byte-identical.
    injected = dict(original)
    injected["dm"] += "\nEXPORT_SYMBOL_GPL(dm_get_live_table);\n"
    if injected["dm"] == original["dm"]:
        fail("invalid no-op export mutation")
    try:
        validate_sources(injected)
    except AssertionError as error:
        if "Round048" not in str(error):
            raise
    else:
        fail("fabricated public table-lifetime API unexpectedly accepted")
    print(HOSTILE_EXPECTED)
    print("ROUND048_FAKE_EXPORTED_TABLE_API_REJECTED_PASS")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--kernel-root", type=Path, required=True)
    args = parser.parse_args()
    sources = load_sources(args.kernel_root)
    validate_sources(sources)
    run_hostile_sources(sources)
    print(EXPECTED)
    print("ROUND048_ORIGINAL_LINUX_DM_PINNED_COMMIT_" + ORIGINAL_LINUX_COMMIT)
    print("ROUND048_NO_RETAINED_EXTERNAL_TABLE_EXPORT_NO_SOURCE_TO_DM_AUTHORITY")


if __name__ == "__main__":
    main()
