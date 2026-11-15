#!/usr/bin/env python3
"""Rootless production-source contract check, not a kernel/runtime test."""
from pathlib import Path
import re
import sys

SOURCE = Path(__file__).resolve().parents[3] / "src/kernel/dm-target.c"

def exactly_one(text: str, expression: str, name: str) -> None:
    matches = list(re.finditer(expression, text, re.MULTILINE | re.DOTALL))
    if len(matches) != 1:
        raise AssertionError(f"{name}: expected one source occurrence, got {len(matches)}")

def validate_source_text(source: str) -> None:
    exactly_one(source, r"enum swapz_write_origin \{[^}]*\};", "origin semantics")
    exactly_one(source,
        r"entry->write_origin = SWAPZ_WRITE_ORIGIN_ORDINARY_OR_UNKNOWN;\n"
        r"#ifdef BIO_HAS_ZSWAP_STORED_WRITEBACK_ORIGIN\n"
        r"(?:(?!#endif).)*"
        r"bio_is_zswap_stored_writeback\(bio\)\).*?\n#endif",
        "only guarded positive classifier")
    if source.count("swapz_count_verified_zswap_writeback_commit(ctx,") != 4:
        raise AssertionError("four final foreground-commit sites required")
    if source.count("entry->write_origin") != 4:
        raise AssertionError("origin may be consulted only at admission and commit")
    if source.count("bio_is_zswap_stored_writeback(bio)") != 1:
        raise AssertionError("single positive origin authority required")
    body = source[source.index("static int swapz_map("):]
    anchors = (
        "entry->write_origin = SWAPZ_WRITE_ORIGIN_ORDINARY_OR_UNKNOWN",
        "entry->write_origin = SWAPZ_WRITE_ORIGIN_ZSWAP_STORED_WRITEBACK",
        "if (!ctx->accepting)",
        "atomic64_inc(&ctx->verified_zswap_origin_admitted)",
        "list_add_tail(&entry->list, &ctx->incoming)",
    )
    positions = [body.index(anchor) for anchor in anchors]
    if positions != sorted(positions) or len(set(positions)) != len(positions):
        raise AssertionError("descriptor reset / requeue / FIFO order changed")
    for counter in ("verified_zswap_origin_admitted",
                    "foreground_committed_verified_zswap_writeback"):
        if source.count(f"atomic64_set(&ctx->{counter}, 0)") != 1:
            raise AssertionError(f"missing mapper constructor counter reset: {counter}")
    for marker in (
        "verified_zswap_origin_admitted=%llu",
        "foreground_committed_verified_zswap_writeback=%llu",
        "origin_carrier_compiled=1",
        "origin_carrier_compiled=0",
        "atomic64_inc(&ctx->verified_zswap_origin_admitted)",
        "atomic64_inc(&ctx->foreground_committed_verified_zswap_writeback)",
    ):
        if source.count(marker) != 1:
            raise AssertionError("missing or ambiguous origin accounting: " + marker)
    for pattern in (
        r"ctx->compressed_pages\+\+;\s*swapz_count_verified_zswap_writeback_commit\(ctx,\s*inflight->bios\[index\]\)",
        r"ctx->compressed_pages\+\+;\s*swapz_count_verified_zswap_writeback_commit\(ctx, bio\);\s*swapz_complete\(bio, 0\)",
        r"ctx->raw_pages\+\+;\s*ctx->logical_write_bytes \+= SWAPZ_BLOCK_BYTES;\s*swapz_count_verified_zswap_writeback_commit\(ctx, bio\)",
        r"ctx->zero_elided_pages\+\+;\s*swapz_count_verified_zswap_writeback_commit\(ctx, bio\)",
    ):
        exactly_one(source, pattern, "authoritative success count")
    body = source[source.index("static int swapz_map("):]
    requeue = body.index("if (!ctx->accepting)")
    counted = body.index("atomic64_inc(&ctx->verified_zswap_origin_admitted)")
    queued = body.index("list_add_tail(&entry->list, &ctx->incoming)")
    if not requeue < counted < queued:
        raise AssertionError("requeued/denied BIO counted as accepted")
    if "raw_committed_verified_origin_bypass" in source:
        raise AssertionError("Phase B origin bypass must not be integrated")


def replace_exactly_once(source: str, old: str, new: str) -> str:
    if source.count(old) != 1:
        raise AssertionError("mutation anchor count changed: " + old[:72])
    return source.replace(old, new, 1)


def replace_pattern_once(source: str, expression: str, new: str) -> str:
    matches = list(re.finditer(expression, source, re.MULTILINE | re.DOTALL))
    if len(matches) != 1:
        raise AssertionError("mutation regex source occurrence changed")
    match = matches[0]
    return source[:match.start()] + new + source[match.end():]


def verify_strict_phase_a_contract(source: str) -> None:
    exactly_one(source,
        r"#ifdef BIO_HAS_ZSWAP_STORED_WRITEBACK_ORIGIN\n"
        r"\s*if\s*\(\s*bio_op\(bio\)\s*==\s*REQ_OP_WRITE\s*&&\s*"
        r"count\s*==\s*SWAPZ_SECTORS\s*&&\s*"
        r"bio->bi_iter\.bi_size\s*==\s*SWAPZ_BLOCK_BYTES\s*&&\s*"
        r"bio_is_zswap_stored_writeback\(bio\)\s*\)\s*"
        r"entry->write_origin\s*=\s*SWAPZ_WRITE_ORIGIN_ZSWAP_STORED_WRITEBACK;\s*#endif",
        "exact optional carrier guard, request class, and 4096-byte length")
    map_start = source.index("static int swapz_map(")
    map_region = source[map_start:]
    next_function = map_region.find("\nstatic ", len("static int swapz_map("))
    if next_function >= 0:
        map_region = map_region[:next_function]
    if "entry->preparation_force_raw = true;" in map_region:
        raise AssertionError("Phase A must not force RAW in map admission")
    if source.count("->write_origin") != 4:
        raise AssertionError("source origin used outside admission/commit boundaries")
    if source.count('DMEMIT(" origin_carrier_compiled=1");') != 1 or \
       source.count('DMEMIT(" origin_carrier_compiled=0");') != 1:
        raise AssertionError("origin carrier compilation fallback missing")
    exactly_one(source,
        r"swapz_finish_raw\([^;]*\);\s*"
        r"error\s*=\s*swapz_preserve_first_error\(error,\s*finish_error\);\s*"
        r"if\s*\(!error\)\s*\{\s*ctx->raw_pages\+\+;\s*"
        r"ctx->logical_write_bytes\s*\+=\s*SWAPZ_BLOCK_BYTES;\s*"
        r"swapz_count_verified_zswap_writeback_commit\(ctx,\s*bio\);",
        "RAW commit hook must follow successful authority finish")
    exactly_one(source,
        r"ctx->zero_elided_pages\+\+;\s*"
        r"swapz_count_verified_zswap_writeback_commit\(ctx,\s*bio\);\s*\}\s*"
        r"swapz_complete\(bio,\s*error\);",
        "zero publication hook must occur before success completion")


def run_negative_mutations(source: str) -> int:
    reset = "entry->write_origin = SWAPZ_WRITE_ORIGIN_ORDINARY_OR_UNKNOWN;"
    admitted = "atomic64_inc(&ctx->verified_zswap_origin_admitted);"
    async_hook = (r"swapz_count_verified_zswap_writeback_commit"
                  r"\(ctx,\s*inflight->bios\[index\]\);")
    sync_hook = (r"swapz_count_verified_zswap_writeback_commit"
                 r"\(ctx,\s*bio\);\s*swapz_complete\(bio,\s*0\);")
    zero_hook = (r"ctx->zero_elided_pages\+\+;\s*"
                 r"swapz_count_verified_zswap_writeback_commit\(ctx,\s*bio\);")
    controls = [
        ("missing UNKNOWN reset", lambda: replace_exactly_once(source, reset, "")),
        ("positive default on descriptor reuse",
         lambda: replace_exactly_once(source, reset,
             "entry->write_origin = SWAPZ_WRITE_ORIGIN_ZSWAP_STORED_WRITEBACK;")),
        ("origin reset after FIFO publication", lambda: replace_exactly_once(
            replace_exactly_once(source, reset, ""),
            "list_add_tail(&entry->list, &ctx->incoming);",
            "list_add_tail(&entry->list, &ctx->incoming);\n\t" + reset)),
        ("missing feature guard", lambda: replace_exactly_once(source,
            "#ifdef BIO_HAS_ZSWAP_STORED_WRITEBACK_ORIGIN\n\tif (bio_op(bio)",
            "\tif (bio_op(bio)")),
        ("READ origin accepted", lambda: replace_exactly_once(source,
            "if (bio_op(bio) == REQ_OP_WRITE && count == SWAPZ_SECTORS &&",
            "if (count == SWAPZ_SECTORS &&")),
        ("non-4KiB sectors accepted", lambda: replace_exactly_once(source,
            "count == SWAPZ_SECTORS &&\n\t    bio->bi_iter.bi_size",
            "bio->bi_iter.bi_size")),
        ("non-4KiB byte length accepted", lambda: replace_exactly_once(source,
            "bio->bi_iter.bi_size == SWAPZ_BLOCK_BYTES &&",
            "bio->bi_iter.bi_size >= SWAPZ_BLOCK_BYTES &&")),
        ("admission count skipped", lambda: replace_exactly_once(source,
            admitted, "")),
        ("double admission count", lambda: replace_exactly_once(source,
            admitted, admitted + "\n\t\t" + admitted)),
        ("admission count before accept", lambda: replace_exactly_once(source,
            "\t\tif (!ctx->accepting) {",
            "\t\t" + admitted + "\n\t\tif (!ctx->accepting) {")),
        ("async commit missing", lambda: replace_pattern_once(source,
            async_hook, "")),
        ("async commit doubled", lambda: replace_pattern_once(source,
            async_hook,
            "swapz_count_verified_zswap_writeback_commit(ctx, inflight->bios[index]);\n"
            "\t\t\tswapz_count_verified_zswap_writeback_commit(ctx, inflight->bios[index]);")),
        ("sync commit missing", lambda: replace_pattern_once(source,
            sync_hook, "swapz_complete(bio, 0);")),
        ("RAW error counted", lambda: replace_exactly_once(source,
            "error = swapz_preserve_first_error(error, finish_error);\n\tif (!error) {",
            "error = swapz_preserve_first_error(error, finish_error);\n\tif (error) {")),
        ("zero success count missing", lambda: replace_pattern_once(source,
            zero_hook, "ctx->zero_elided_pages++;")),
        ("commit count ignores origin", lambda: replace_exactly_once(source,
            "if (entry->write_origin == SWAPZ_WRITE_ORIGIN_ZSWAP_STORED_WRITEBACK)\n"
            "\t\tatomic64_inc(&ctx->foreground_committed_verified_zswap_writeback);",
            "atomic64_inc(&ctx->foreground_committed_verified_zswap_writeback);")),
        ("origin-dependent RAW routing", lambda: replace_exactly_once(source,
            "entry->preparation_force_raw = false;",
            "entry->preparation_force_raw = true;")),
        ("counter constructor reset missing", lambda: replace_exactly_once(source,
            "atomic64_set(&ctx->foreground_committed_verified_zswap_writeback, 0);",
            "")),
        ("origin carrier claimed on stock headers", lambda: replace_exactly_once(source,
            'DMEMIT(" origin_carrier_compiled=0");',
            'DMEMIT(" origin_carrier_compiled=1");')),
        ("Phase B origin bypass introduced", lambda:
            source + "\nstatic unsigned long raw_committed_verified_origin_bypass;\n"),
    ]
    detected = 0
    for name, mutate in controls:
        changed = mutate()
        if changed == source:
            raise AssertionError("negative control did not mutate source: " + name)
        try:
            validate_source_text(changed)
            verify_strict_phase_a_contract(changed)
        except (AssertionError, ValueError):
            detected += 1
        else:
            raise AssertionError("negative control unexpectedly passed: " + name)
    return detected


def main() -> int:
    source = SOURCE.read_text(encoding="utf-8")
    validate_source_text(source)
    verify_strict_phase_a_contract(source)
    detected = run_negative_mutations(source)
    print(f"PASS: real production-C Phase A source contract; {detected} negative mutations rejected")
    print("Evidence class: rootless source-contract only; no genuine kernel writeback")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (AssertionError, OSError, ValueError) as failure:
        print(f"FAIL: {failure}", file=sys.stderr)
        raise SystemExit(1)
