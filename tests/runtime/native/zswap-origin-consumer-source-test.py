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

def main() -> int:
    source = SOURCE.read_text(encoding="utf-8")
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
    print("PASS: frozen actual source boundaries, fallback, commit hooks, INFO fields")
    print("Evidence class: rootless source contract only")
    return 0

if __name__ == "__main__":
    try:
        sys.exit(main())
    except (AssertionError, OSError, ValueError) as failure:
        print(f"FAIL: {failure}", file=sys.stderr)
        raise SystemExit(1)

