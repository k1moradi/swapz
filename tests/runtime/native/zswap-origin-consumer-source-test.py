#!/usr/bin/env python3
"""Rootless production-source contract check, not a kernel/runtime test."""
from functools import lru_cache
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

SOURCE = Path(__file__).resolve().parents[3] / "src/kernel/dm-target.c"

def exactly_one(text: str, expression: str, name: str) -> None:
    matches = list(re.finditer(expression, text, re.MULTILINE | re.DOTALL))
    if len(matches) != 1:
        raise AssertionError(f"{name}: expected one source occurrence, got {len(matches)}")

def validate_source_text(source: str) -> None:
    exactly_one(source, r"enum swapz_write_origin \{[^}]*\};", "origin semantics")
    exactly_one(source,
        r"entry->write_origin = SWAPZ_WRITE_ORIGIN_ORDINARY_OR_UNKNOWN;\n"
        r"\s*entry->origin_commit_counted = false;\n"
        r"#ifdef BIO_HAS_ZSWAP_STORED_WRITEBACK_ORIGIN\n"
        r"(?:(?!#endif).)*"
        r"bio_is_zswap_stored_writeback\(bio\)\).*?\n#endif",
        "only guarded positive classifier")
    # Four ordinary sites plus the separately guarded typed owner.
    if source.count("swapz_count_verified_zswap_writeback_commit(ctx,") != 5:
        raise AssertionError("four ordinary and one typed foreground-commit sites required")
    verify_typed_foreground_commit(source)
    if source.count("entry->write_origin") != 4:
        raise AssertionError("origin may be consulted only at admission and commit")
    if source.count("entry->origin_commit_counted") != 3:
        raise AssertionError("once-only origin flag must have one reset, test and mark")
    exactly_one(source,
        r"entry->write_origin = SWAPZ_WRITE_ORIGIN_ORDINARY_OR_UNKNOWN;\s*"
        r"entry->origin_commit_counted = false;\s*"
        r"#ifdef BIO_HAS_ZSWAP_STORED_WRITEBACK_ORIGIN",
        "reused BIO origin and once-only state reset")
    exactly_one(source,
        r"if \(entry->write_origin != SWAPZ_WRITE_ORIGIN_ZSWAP_STORED_WRITEBACK \|\|\s*"
        r"entry->origin_commit_counted\)\s*return;\s*"
        r"entry->origin_commit_counted = true;\s*"
        r"atomic64_inc\(&ctx->foreground_committed_verified_zswap_writeback\);",
        "ordered-owner idempotent authenticated authority count")
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


def typed_commit_region(source: str) -> str:
    start = "static bool swapz_round091_process_candidate("
    end = "\n#endif\n\nstatic void swapz_process("
    if source.count(start) != 1 or end not in source.split(start, 1)[1]:
        raise AssertionError("typed owner boundary missing")
    return source.split(start, 1)[1].split(end, 1)[0]


# The legacy target has no cancellation witness flag. On newer targets the
# flag may suppress evidence loss only after the exact reserved credit is
# canceled successfully. Keep both canonical shapes, not an optional wildcard.
LEGACY_DECLINE = (
    r"if \(entry->observation_operation\)\s*swapz_scope_observe_invalid\(\);")
GUARDED_DECLINE = (
    r"if \(entry->observation_operation\s*"
    r"#if defined\(SWAPZ_ROUND104_INTEGRATION_TEST\)\s*"
    r"&& !entry->observation_fallback\s*#endif\s*\)\s*"
    r"swapz_scope_observe_invalid\(\);")


def has_guarded_fallback(source: str) -> bool:
    # Removing the flag alone must not silently select the historical path.
    return any(marker in source for marker in (
        "observation_fallback", "observation_plain_write",
        "observation_claim_lower_failed", "swapz_scope_retire"))


@lru_cache(maxsize=1)
def masked_c(source: str) -> str:
    return re.sub(r'//[^\n]*|/\*[\s\S]*?\*/|"(?:\\.|[^"\\\n])*"|'
                  r"'(?:\\.|[^'\\\n])*'",
                  lambda match: re.sub(r"[^\n]", " ", match.group()), source)


def exact_function(source: str, name: str) -> str:
    """Extract one complete static definition; never audit a truncated prefix."""
    masked = masked_c(source)
    matches = list(re.finditer(r"(?m)^static (?:bool|void|int) " +
                               re.escape(name) + r"\(", masked))
    if len(matches) != 1:
        raise AssertionError("ambiguous function: " + name)
    start = matches[0].start()
    opening = masked.find("{", matches[0].end())
    if opening < 0 or ";" in masked[matches[0].end():opening]:
        raise AssertionError("malformed signature: " + name)
    depth = 0
    for brace in re.finditer(r"[{}]", masked[opening:]):
        position = opening + brace.start()
        depth += 1 if brace.group() == "{" else -1
        if not depth:
            if (masked[position - 1] != "\n" or
                    masked[position + 1:position + 2] != "\n" or
                    re.search(r"(?m)^static ", masked[opening + 1:position])):
                raise AssertionError("malformed function boundary: " + name)
            return source[start:position + 1]
    raise AssertionError("unterminated function: " + name)


def verify_guarded_fallback(source: str, region: str) -> None:
    """Verify actual scoped transaction, retained clone and completion paths."""
    transaction = exact_function(source, "swapz_scope_transaction")
    # Reserve failure has no credit: only integrity/I/O errors are terminal.
    # The other refusal must cancel the *same* credit before fallback.
    exactly_one(transaction,
        r"\*error = swapz_shared_storage_reserve\(ctx->original_storage, spec, input, &credit\);\s*"
        r"if \(\*error\) \{\s*#if defined\(SWAPZ_SCOPED_TARGET_OBSERVATION\)\s*"
        r"swapz_scope_observe_simple\(entry, SWAPZ_OBS_REFUSE, 0, \*error\);\s*"
        r"if \(\*error != -EUCLEAN && \*error != -EIO\) \{\s*"
        r"swapz_scope_observe_simple\(entry, SWAPZ_OBS_FALLBACK, 0, 0\);\s*"
        r"#if defined\(SWAPZ_ROUND104_INTEGRATION_TEST\)\s*"
        r"/\*[^*]*\*+(?:[^/*][^*]*\*+)*/\s*swapz_scope_observe_invalid\(\);\s*"
        r"#endif\s*\}\s*#endif\s*return \*error == -EUCLEAN \|\| \*error == -EIO;\s*\}",
        "reserve failure without credit must not claim cancellation proof")
    exactly_one(transaction,
        r"refused = swapz_round091_claim_reserved\(claim, credit\);\s*if \(refused\) \{\s*"
        r"#if defined\(SWAPZ_SCOPED_TARGET_OBSERVATION\)\s*"
        r"swapz_scope_observe_simple\(entry, SWAPZ_OBS_REFUSE, 0, refused\);\s*#endif\s*"
        r"\*error = swapz_shared_storage_cancel_reserved\(ctx->original_storage, credit\);\s*"
        r"#if defined\(SWAPZ_SCOPED_TARGET_OBSERVATION\)\s*if \(!\*error\) \{\s*"
        r"swapz_scope_observe_credit\(entry, SWAPZ_OBS_CANCEL, credit\);\s*"
        r"swapz_scope_observe_simple\(entry, SWAPZ_OBS_FALLBACK, 0, 0\);\s*"
        r"#if defined\(SWAPZ_ROUND104_INTEGRATION_TEST\)\s*"
        r"entry->observation_fallback = true;\s*#endif\s*\} else\s*"
        r"swapz_scope_observe_invalid\(\);\s*#endif\s*return \*error != 0;\s*\}",
        "exact cancellation before fallback; cancellation failure remains terminal")
    commit = "*error = swapz_shared_storage_commit_reserved(ctx->original_storage, credit);"
    if (transaction.count(commit) != 1 or
            transaction.count("swapz_shared_storage_reserve(") != 1 or
            transaction.count("swapz_shared_storage_cancel_reserved(") != 1 or
            transaction.count("swapz_round091_claim_reserved(") != 1 or
            transaction.count("SWAPZ_OBS_FALLBACK") != 2 or
            transaction.count("SWAPZ_OBS_CANCEL") != 1 or
            transaction.count("return ") != 3 or
            transaction.count("goto ") != 0):
        raise AssertionError("typed scoped transaction has ambiguous ownership")
    committed = transaction[transaction.index(commit):]
    exactly_one(committed, r"return true;\s*\}$", "postclaim commit is always terminal")
    if ("SWAPZ_OBS_FALLBACK" in committed or
            "swapz_shared_storage_cancel_reserved(" in committed or
            transaction.index("return *error != 0;") > transaction.index(commit)):
        raise AssertionError("postclaim fallback or cancellation")
    # One guarded witness writer and one descriptor reset, even on reuse.
    if (source.count("entry->observation_fallback = true;") != 1 or
            source.count("entry->observation_fallback = false;") != 1):
        raise AssertionError("fallback witness writer/reset not unique")
    mapping = exact_function(source, "swapz_map")
    exactly_one(mapping,
        r"entry->observation_plain_write = false;\s*entry->observation_fallback = false;\s*"
        r"entry->observation_claim_lower_failed = false;",
        "fallback witness reset at descriptor reuse")
    # Historical unscoped branch retains the same credit and terminal contract.
    legacy = exact_function(source, "swapz_round091_reserve_claim_commit")
    exactly_one(legacy,
        r"\*error = swapz_shared_storage_reserve\(storage, spec, input, &credit\);\s*"
        r"if \(\*error\)\s*return \*error == -EUCLEAN \|\| \*error == -EIO;\s*"
        r"if \(try_claim\(context, credit\)\) \{\s*"
        r"\*error = swapz_shared_storage_cancel_reserved\(storage, credit\);\s*"
        r"return \*error != 0;\s*\}\s*/\*[^*]*\*+(?:[^/*][^*]*\*+)*/\s*"
        r"\*error = swapz_shared_storage_commit_reserved\(storage, credit\);\s*"
        r"return true;\s*\}$", "legacy credit ownership and terminal commit")
    if legacy.count("return ") != 3:
        raise AssertionError("ambiguous legacy terminal ownership")
    # The accepted clone is the sole completion owner. The original is used
    # only for MM candidate lookup, never completed by the typed path.
    candidate = exact_function(source, "swapz_round090_candidate_get")
    exactly_one(candidate,
        r"origin = dm_swapz_round090_selected_origin\(ti, bio\);\s*"
        r"if \(!origin \|\| swapz_mm_candidate_get\(origin, ref\)\)\s*return;",
        "selected original lookup is distinct from clone completion")
    claim = exact_function(source, "swapz_round091_claim_reserved")
    exactly_one(claim,
        r"selected = dm_swapz_round091_accepted_clone_matches\(ctx->target, entry->bio\) &&",
        "claim uses retained accepted clone")
    process = exact_function(source, "swapz_process")
    exactly_one(process,
        r"struct swapz_bio_ref \*entry = dm_per_bio_data\(bio, sizeof\(\*entry\)\);\s*"
        r"#if defined\(SWAPZ_ROUND098_SCOPED_TARGET_TEST\)\s*"
        r"if \(swapz_round091_process_candidate\(ctx, entry,\s*entry->original_scope_identity != 0\)\)\s*"
        r"#else\s*if \(swapz_round091_process_candidate\(ctx, entry,\s*"
        r"swapz_round091_ordered_claim_permitted\(\)\)\)\s*#endif\s*return;\s*\}\s*#endif",
        "typed terminal return prevents ordinary continuation")
    completion = exact_function(source, "swapz_complete")
    release = "swapz_round091_release_candidate(ctx, entry);"
    if (completion.count(release) != 1 or completion.count("bio_endio(bio);") != 1 or
            completion.index(release) >= completion.index("bio_endio(bio);") or
            region.count(release) != 1 or
            region.count("return true;") != 1 or region.count("return false;") != 2 or
            len(re.findall(r"\breturn\b", masked_c(region))) != 3):
        raise AssertionError("typed terminal/release ownership ambiguous")
    release_body = exact_function(source, "swapz_round091_release_candidate")
    exactly_one(release_body,
        r"if \(!entry->original_candidate.broker\)\s*return;\s*"
        r"/\*[^*]*\*+(?:[^/*][^*]*\*+)*/\s*"
        r"ctx->original_release_ref = entry->original_candidate;\s*"
        r"#if defined\(SWAPZ_SCOPED_TARGET_OBSERVATION\)\s*"
        r"ctx->observation_release_operation = entry->observation_operation;\s*"
        r"ctx->observation_release_descriptor = entry->observation_descriptor;\s*#endif\s*"
        r"entry->original_candidate = \(struct swapz_ticket_ref\)\{\};\s*"
        r"entry->original_view = \(struct swapz_ticket_view\)\{\};\s*"
        r"entry->original_registration_epoch = 0;\s*entry->original_claimed = false;\s*"
        r"WARN_ON_ONCE\(!queue_work\(system_unbound_wq, &ctx->original_release_work\)\);\s*\}$",
        "candidate lease transfer and descriptor clear before queued put")
    release_worker = exact_function(source, "swapz_round090_release_work")
    exactly_one(release_worker,
        r"#if defined\(SWAPZ_SCOPED_TARGET_OBSERVATION\)\s*"
        r"int error = swapz_ticket_put\(&ctx->original_release_ref\);\s*"
        r"swapz_scope_observe_release\(ctx->observation_release_operation,\s*"
        r"ctx->observation_release_descriptor, error\);\s*"
        r"ctx->observation_release_operation = 0;\s*"
        r"ctx->observation_release_descriptor = 0;\s*"
        r"if \(WARN_ON_ONCE\(error\)\)\s*return;\s*"
        r"/\*[^*]*\*+(?:[^/*][^*]*\*+)*/\s*#else\s*"
        r"if \(WARN_ON_ONCE\(swapz_ticket_put\(&ctx->original_release_ref\)\)\)\s*return;\s*"
        r"/\*[^*]*\*+(?:[^/*][^*]*\*+)*/\s*#endif\s*"
        r"atomic_set_release\(&ctx->original_release_busy, 0\);\s*\}$",
        "actual candidate put before release slot reuse")
    # No extra transfer/claim/completion path can be inserted into the typed
    # owner after the transaction decision.
    terminal_start = region.index("#if defined(SWAPZ_ROUND098_SCOPED_TARGET_TEST)",
                                  region.index("swapz_invalidate_read_caches(ctx);"))
    terminal = region[terminal_start:]
    if terminal.count("goto decline;") != 2 or terminal.count("goto complete;") != 0:
        raise AssertionError("unexpected postclaim branch in typed terminal owner")


def verify_typed_foreground_commit(source: str) -> None:
    region = typed_commit_region(source)
    # R098 adds an exclusive scoped transaction branch; both real branches
    # must refuse before the one success accounting block.
    exactly_one(region,
        r"#if defined\(SWAPZ_ROUND098_SCOPED_TARGET_TEST\)\s*"
        r"if \(!swapz_scope_transaction\(ctx, &spec, &input, &claim_context, &error\)\)"
        r"\s*goto decline;\s*#else\s*"
        r"if \(!swapz_round091_reserve_claim_commit\(ctx->original_storage, &spec,"
        r"\s*&input, swapz_round091_claim_reserved, &claim_context, &error\)\)"
        r"\s*goto decline;\s*#endif\s*if \(!error && entry->original_claimed\) \{"
        r"\s*entry->published_ns = ktime_get_ns\(\);"
        r"\s*ctx->logical_write_bytes \+= SWAPZ_BLOCK_BYTES;"
        r"\s*ctx->compressed_pages\+\+;"
        r"\s*swapz_count_verified_zswap_writeback_commit\(ctx, entry->bio\);\s*\}",
        "typed claimed publication success before accounting")
    # A failed cancellation or impossible unclaimed success is quarantined.
    exactly_one(region,
        r"\} else if \(!entry->original_claimed\) \{\s*/\*[^*]*\*+(?:[^/*][^*]*\*+)*/"
        r"\s*swapz_fail\(ctx, error \? error : -EUCLEAN\);"
        r"\s*if \(!error\)\s*error = -EUCLEAN;\s*\}\s*complete:",
        "typed unclaimed terminal invariant failure is quarantined")
    guarded = has_guarded_fallback(source)
    decline = GUARDED_DECLINE if guarded else LEGACY_DECLINE
    exactly_one(region, r"complete:\s*swapz_complete\(entry->bio, error\);\s*return true;"
                 r"\s*decline:\s*#if defined\(SWAPZ_SCOPED_TARGET_OBSERVATION\)\s*"
                 r"/\*[^*]*\*+(?:[^/*][^*]*\*+)*/\s*" + decline +
                 r"\s*#endif\s*swapz_round091_release_candidate\(ctx, entry\);\s*return false;",
                 "typed terminal owner versus ordinary fallback")
    if guarded:
        verify_guarded_fallback(source, region)
    if region.count("swapz_complete(") != 1 or region.count(
            "swapz_count_verified_zswap_writeback_commit(") != 1:
        raise AssertionError("typed owner duplicate completion/accounting")


def replace_exactly_once(source: str, old: str, new: str) -> str:
    if source.count(old) != 1:
        raise AssertionError("mutation anchor count changed: " + old[:72])
    return source.replace(old, new, 1)


def original_origin_attribution_bounds(source: str) -> tuple[int, int]:
    """Locate the ONE real provenance gate, never the Round043 observer."""
    beginning = (
        "\tentry->write_origin = SWAPZ_WRITE_ORIGIN_ORDINARY_OR_UNKNOWN;\n"
        "\tentry->origin_commit_counted = false;\n"
        "#ifdef BIO_HAS_ZSWAP_STORED_WRITEBACK_ORIGIN\n"
    )
    if source.count(beginning) != 1:
        raise AssertionError("original STORED origin attribution gate drift")
    start = source.index(beginning)
    end_marker = "\n#endif"
    end = source.find(end_marker, start + len(beginning))
    if end < 0:
        raise AssertionError("original STORED origin attribution endif missing")
    end += len(end_marker)
    if source[start:end].count(
            "entry->write_origin = SWAPZ_WRITE_ORIGIN_ZSWAP_STORED_WRITEBACK;") != 1:
        raise AssertionError("original STORED positive attribution not unique")
    return start, end


def replace_original_origin_attribution_once(
        source: str, old: str, new: str) -> str:
    """Mutate original guarded attribution only; preserve all other C bytes."""
    start, end = original_origin_attribution_bounds(source)
    original_gate = source[start:end]
    changed_gate = replace_exactly_once(original_gate, old, new)
    return source[:start] + changed_gate + source[end:]


def verify_scoped_original_origin_mutations(source: str) -> None:
    """Prove that duplicate Round043 geometry cannot steer old 24 oracles."""
    old = "count == SWAPZ_SECTORS &&\n\t    bio->bi_iter.bi_size"
    start, end = original_origin_attribution_bounds(source)
    if source.count(old) < 2 or source[start:end].count(old) != 1:
        raise AssertionError("original versus observer geometry not independent")
    changed = replace_original_origin_attribution_once(
        source, old, "bio->bi_iter.bi_size")
    if (changed[:start] != source[:start] or
            changed[start + len(source[start:end]) - len(old) +
                    len("bio->bi_iter.bi_size"):] != source[end:]):
        raise AssertionError("scoped original mutation changed unrelated C")
    if changed.count(old) != source.count(old) - 1:
        raise AssertionError("original mutation did not leave observer intact")
    try:
        validate_source_text(changed)
        verify_strict_phase_a_contract(changed)
    except (AssertionError, ValueError):
        pass
    else:
        raise AssertionError("mutated original STORED geometry accepted")
    observer_begin = "/* ROUND043_DM_REAL_MAP_CALLSITE_EXACT_START */"
    observer_end = "/* ROUND043_DM_REAL_MAP_CALLSITE_EXACT_END */"
    if source.count(observer_begin) != 1 or source.count(observer_end) != 1:
        raise AssertionError("original source Round043 observer markers drift")
    before, remainder = source.split(observer_begin, 1)
    observer, after = remainder.split(observer_end, 1)
    if observer.count(old) != 1:
        raise AssertionError("Round043 observer geometry collision disappeared")
    observer_only = (before + observer_begin +
                     observer.replace(old, "bio->bi_iter.bi_size", 1) +
                     observer_end + after)
    other_start, other_end = original_origin_attribution_bounds(observer_only)
    if observer_only[other_start:other_end] != source[start:end]:
        raise AssertionError("observation-only mutation altered original gate")
    validate_source_text(observer_only)
    verify_strict_phase_a_contract(observer_only)
    print("PASS: Round044 real origin scoped mutation; observer untouched")


def replace_pattern_once(source: str, expression: str, new: str) -> str:
    matches = list(re.finditer(expression, source, re.MULTILINE | re.DOTALL))
    if len(matches) != 1:
        raise AssertionError("mutation regex source occurrence changed")
    match = matches[0]
    return source[:match.start()] + new + source[match.end():]


def verify_guarded_raw_commit(source: str) -> None:
    """The intervening observer must not modify the authority result."""
    raw = exact_function(source, "swapz_raw_write")
    exactly_one(raw,
        r"bool witness = observed && \(entry->observation_plain_write \|\| entry->observation_fallback\) &&\s*"
        r"!entry->original_claimed && \(bio->bi_opf & REQ_FUA\);\s*"
        r"if \(observed && !witness\)\s*swapz_scope_observe_invalid\(\);",
        "ordinary RAW/FUA witness excludes claimed typed requests")
    exactly_one(raw,
        r"finish_error = swapz_finish_raw\(&ctx->authority, transaction, ctx->input_page,\s*"
        r"completed, error\);\s*error = swapz_preserve_first_error\(error, finish_error\);\s*"
        r"#if defined\(SWAPZ_ROUND104_INTEGRATION_TEST\)\s*if \(witness\) \{\s*"
        r"const struct swapz_map \*map = &ctx->maps\[logical\];\s*"
        r"if \(!error && map->valid && map->raw &&\s*"
        r"map->start_block == transaction->start_block &&\s*"
        r"map->generation == transaction->records\[0\]\.generation &&\s*"
        r"map->payload_length == SWAPZ_BLOCK_BYTES\) \{\s*"
        r"struct swapz_observation_record record = \{\s*"
        r"\.event = SWAPZ_OBS_PUBLISH, \.operation = entry->observation_operation,\s*"
        r"\.extent = entry->observation_extent, \.new_generation = map->generation,\s*"
        r"\.compressed_length = SWAPZ_BLOCK_BYTES, \.decoded_length = SWAPZ_BLOCK_BYTES,\s*\};\s*"
        r"memcpy\(record.compressed_sha256, entry->observation_compressed_sha256, 32\);\s*"
        r"memcpy\(record.page_sha256, entry->observation_compressed_sha256, 32\);\s*"
        r"if \(logical && logical <= SWAPZ_ROUND094_GENERATION_PAGES\)\s*"
        r"memset\(&ctx->observation_extent_by_page\[logical - 1U\],\s*"
        r"0, sizeof\(ctx->observation_extent_by_page\[0\]\)\);\s*"
        r"swapz_scope_observe_event\(&record, NULL, 0\);\s*\} else \{\s*"
        r"swapz_scope_observe_invalid\(\);\s*\}\s*\}\s*#endif\s*"
        r"if \(!error\) \{\s*ctx->raw_pages\+\+;\s*"
        r"ctx->logical_write_bytes \+= SWAPZ_BLOCK_BYTES;\s*"
        r"swapz_count_verified_zswap_writeback_commit\(ctx, bio\);\s*\}\s*return error;\s*\}$",
        "RAW commit hook must follow successful authority finish and non-mutating witness")


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
    if has_guarded_fallback(source):
        verify_guarded_raw_commit(source)
    else:
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
    once_reset = "entry->origin_commit_counted = false;"
    once_guard = ("if (entry->write_origin != SWAPZ_WRITE_ORIGIN_ZSWAP_STORED_WRITEBACK ||\n"
                  "\t    entry->origin_commit_counted)\n\t\treturn;")
    once_mark = "entry->origin_commit_counted = true;"
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
        ("missing feature guard", lambda: replace_original_origin_attribution_once(source,
            "#ifdef BIO_HAS_ZSWAP_STORED_WRITEBACK_ORIGIN\n\tif (bio_op(bio)",
            "\tif (bio_op(bio)")),
        ("READ origin accepted", lambda: replace_original_origin_attribution_once(source,
            "if (bio_op(bio) == REQ_OP_WRITE && count == SWAPZ_SECTORS &&",
            "if (count == SWAPZ_SECTORS &&")),
        ("non-4KiB sectors accepted", lambda: replace_original_origin_attribution_once(source,
            "count == SWAPZ_SECTORS &&\n\t    bio->bi_iter.bi_size",
            "bio->bi_iter.bi_size")),
        ("non-4KiB byte length accepted", lambda: replace_original_origin_attribution_once(source,
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
            "#endif\n\tif (!error) {\n\t\tctx->raw_pages++;" if has_guarded_fallback(source)
            else "error = swapz_preserve_first_error(error, finish_error);\n\tif (!error) {",
            "#endif\n\tif (error) {\n\t\tctx->raw_pages++;" if has_guarded_fallback(source)
            else "error = swapz_preserve_first_error(error, finish_error);\n\tif (error) {")),
        ("zero success count missing", lambda: replace_pattern_once(source,
            zero_hook, "ctx->zero_elided_pages++;")),
        ("commit count ignores origin", lambda: replace_exactly_once(
            source, once_guard,
            "if (entry->origin_commit_counted)\n\t\treturn;")),
        ("missing once-only reset", lambda: replace_exactly_once(source, once_reset, "")),
        ("reused BIO premarked successful", lambda: replace_exactly_once(
            source, once_reset, "entry->origin_commit_counted = true;")),
        ("repeated success recounts", lambda: replace_exactly_once(
            source, once_guard,
            "if (entry->write_origin != SWAPZ_WRITE_ORIGIN_ZSWAP_STORED_WRITEBACK)\n"
            "\t\treturn;")),
        ("mark after increment", lambda: replace_exactly_once(
            source,
            "\t" + once_mark + "\n"
            "\tatomic64_inc(&ctx->foreground_committed_verified_zswap_writeback);",
            "\tatomic64_inc(&ctx->foreground_committed_verified_zswap_writeback);\n"
            "\t" + once_mark)),
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
    if len(controls) != 24:
        raise AssertionError("the 24 original adversarial controls were weakened")
    return reject_mutations(source, controls)


def run_typed_negative_mutations(source: str) -> int:
    """Keep typed publication controls separate from the stable 24-case ABI."""
    typed_hook = "swapz_count_verified_zswap_writeback_commit(ctx, entry->bio);"
    controls = [
        ("typed commit missing", lambda: replace_exactly_once(source, typed_hook, "")),
        ("typed count doubled", lambda: replace_exactly_once(source, typed_hook, typed_hook + typed_hook)),
        ("typed error counted", lambda: replace_exactly_once(source,
            "if (!error && entry->original_claimed) {", "if (entry->original_claimed) {")),
        ("typed unclaimed counted", lambda: replace_exactly_once(source,
            "if (!error && entry->original_claimed) {", "if (!error) {")),
        ("typed count before commit", lambda: replace_exactly_once(
            replace_exactly_once(source, typed_hook, ""),
            "if (!swapz_round091_reserve_claim_commit(ctx->original_storage, &spec,",
            typed_hook + "\n\tif (!swapz_round091_reserve_claim_commit(ctx->original_storage, &spec,")),
        ("typed completion doubled", lambda: replace_exactly_once(source,
            "complete:\n\tswapz_complete(entry->bio, error);",
            "complete:\n\tswapz_complete(entry->bio, error);\n\tswapz_complete(entry->bio, error);")),
    ]
    if len(controls) != 6:
        raise AssertionError("the six typed publication controls were weakened")
    return reject_mutations(source, controls)


def run_scoped_typed_negative_mutations(source: str) -> int:
    """Additional R098 controls; do not replace the six original typed cases."""
    controls = [
        ("scoped transaction refusal bypassed", lambda: replace_exactly_once(
            source,
            "if (!swapz_scope_transaction(ctx, &spec, &input, &claim_context, &error))\n\t\tgoto decline;",
            "if (!swapz_scope_transaction(ctx, &spec, &input, &claim_context, &error))\n\t\tgoto complete;")),
        ("scoped transaction claim bypassed", lambda: replace_exactly_once(
            source, "if (!swapz_scope_transaction(ctx, &spec, &input, &claim_context, &error))",
            "if (false)")),
        ("unclaimed terminal quarantine skipped", lambda: replace_exactly_once(
            source, "swapz_fail(ctx, error ? error : -EUCLEAN);\n\t\tif (!error)",
            "if (!error)")),
        ("incomplete scoped fallback accepted", lambda: replace_pattern_once(
            source, (GUARDED_DECLINE if has_guarded_fallback(source) else LEGACY_DECLINE) +
            r"\s*#endif\s*swapz_round091_release_candidate\(ctx, entry\);",
            "swapz_round091_release_candidate(ctx, entry);\n#endif")),
    ]
    return reject_mutations(source, controls)


def run_guarded_fallback_negative_mutations(source: str) -> int:
    """Mutate actual R105 path independently of the 34 historical groups."""
    if not has_guarded_fallback(source):
        return 0
    cancel = "*error = swapz_shared_storage_cancel_reserved(ctx->original_storage, credit);"
    commit = "*error = swapz_shared_storage_commit_reserved(ctx->original_storage, credit);"
    release = "swapz_round091_release_candidate(ctx, entry);"
    controls = [
        ("postclaim fallback", lambda: replace_exactly_once(
            source, commit, commit + "\n\treturn false;")),
        ("missing exact cancel", lambda: replace_exactly_once(source, cancel, "*error = 0;")),
        ("wrong cancel credit", lambda: replace_exactly_once(
            source, cancel, cancel.replace(", credit)", ", credit + 1)"))),
        ("cancel failure falls back", lambda: replace_exactly_once(
            source, cancel + "\n#if", cancel + "\n\treturn false;\n#if")),
        ("fallback before cancel", lambda: replace_exactly_once(
            source, cancel, "entry->observation_fallback = true;\n\t\t" + cancel)),
        ("duplicate terminal completion", lambda: replace_exactly_once(
            source, "complete:\n\tswapz_complete(entry->bio, error);",
            "complete:\n\tswapz_complete(entry->bio, error);\n\tswapz_complete(entry->bio, error);")),
        ("omitted decline candidate release", lambda: replace_exactly_once(
            source, release + "\n\treturn false;", "return false;")),
        ("omitted terminal candidate release", lambda: replace_exactly_once(
            source, release + "\n#endif", "\n#endif")),
        ("stale fallback witness", lambda: replace_exactly_once(
            source, "entry->observation_fallback = false;", "")),
        ("wrong clone terminal owner", lambda: replace_exactly_once(
            source, "complete:\n\tswapz_complete(entry->bio, error);",
            "complete:\n\tswapz_complete(original, error);")),
        ("inverted decline witness gate", lambda: replace_exactly_once(
            source, "&& !entry->observation_fallback", "&& entry->observation_fallback")),
        ("omitted actual candidate put", lambda: replace_exactly_once(
            source, "int error = swapz_ticket_put(&ctx->original_release_ref);", "int error = 0;")),
        ("RAW witness accepts claimed typed BIO", lambda: replace_exactly_once(
            source, "!entry->original_claimed && (bio->bi_opf & REQ_FUA)", "(bio->bi_opf & REQ_FUA)")),
        ("RAW witness clears authority error", lambda: replace_exactly_once(
            source, "if (witness) {\n\t\tconst struct swapz_map *map = &ctx->maps[logical];",
            "if (witness) {\n\t\tconst struct swapz_map *map = &ctx->maps[logical];\n\t\terror = 0;")),
        ("RAW witness publishes on error", lambda: replace_exactly_once(
            source, "if (!error && map->valid && map->raw &&", "if (map->valid && map->raw &&")),
        ("duplicate ordinary fallback witness", lambda: replace_exactly_once(
            source, "entry->observation_fallback = true;",
            "swapz_scope_observe_simple(entry, SWAPZ_OBS_FALLBACK, 0, 0);\n"
            "\t\t\tentry->observation_fallback = true;")),
    ]
    return reject_mutations(source, controls)


def reject_mutations(source: str, controls) -> int:
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



def compile_actual_origin_commit_helper(source: str) -> int:
    """Compile the exact committed production C helper, not a Python model.

    The stubs replace only kernel types/counter storage; the function body is
    extracted unmodified from dm-target.c. This proves idempotence in a
    deterministic serial ordered-owner fixture, NOT a loaded-kernel race.
    """
    function_start = source.index(
        "static void swapz_count_verified_zswap_writeback_commit(")
    function_end = source.index("\n}\n", function_start) + len("\n}\n")
    helper = source[function_start:function_end]
    if helper.count("atomic64_inc(") != 1:
        raise AssertionError("extracted original C helper no longer owns one increment")
    prelude = r"""
#include <stdbool.h>
#include <stddef.h>
#include <stdio.h>
enum swapz_write_origin {
    SWAPZ_WRITE_ORIGIN_ORDINARY_OR_UNKNOWN = 0,
    SWAPZ_WRITE_ORIGIN_ZSWAP_STORED_WRITEBACK
};
typedef struct { unsigned long long value; } atomic64_t;
struct swapz_dm {
    atomic64_t foreground_committed_verified_zswap_writeback;
};
struct swapz_bio_ref {
    enum swapz_write_origin write_origin;
    bool origin_commit_counted;
};
struct bio { struct swapz_bio_ref descriptor; };
static void *dm_per_bio_data(struct bio *bio, size_t size)
{
    (void)size;
    return &bio->descriptor;
}
static void atomic64_inc(atomic64_t *counter) { ++counter->value; }
"""
    exercise = r"""
int main(void)
{
    struct swapz_dm context = {0};
    struct bio request = {0};

    /* Ordinary, rejected, READ and requeued requests never call the
     * success helper with authenticated origin. A stale ordinary BIO
     * must also be ignored if a wrong caller invokes this helper. */
    swapz_count_verified_zswap_writeback_commit(&context, &request);
    if (context.foreground_committed_verified_zswap_writeback.value != 0)
        return 10;
    request.descriptor.write_origin = SWAPZ_WRITE_ORIGIN_ZSWAP_STORED_WRITEBACK;
    swapz_count_verified_zswap_writeback_commit(&context, &request);
    swapz_count_verified_zswap_writeback_commit(&context, &request);
    if (context.foreground_committed_verified_zswap_writeback.value != 1 ||
        !request.descriptor.origin_commit_counted)
        return 11;
    /* Two successive admissions reuse the same dm_per_bio_data slot. */
    request.descriptor.write_origin = SWAPZ_WRITE_ORIGIN_ORDINARY_OR_UNKNOWN;
    request.descriptor.origin_commit_counted = false;
    swapz_count_verified_zswap_writeback_commit(&context, &request);
    if (context.foreground_committed_verified_zswap_writeback.value != 1)
        return 12;
    request.descriptor.write_origin = SWAPZ_WRITE_ORIGIN_ZSWAP_STORED_WRITEBACK;
    swapz_count_verified_zswap_writeback_commit(&context, &request);
    swapz_count_verified_zswap_writeback_commit(&context, &request);
    if (context.foreground_committed_verified_zswap_writeback.value != 2)
        return 13;
    puts("PASS exact production C helper ordinary=0 repeated=1 reused=2");
    return 0;
}
"""
    compilers = [name for name in ("gcc", "clang") if shutil.which(name)]
    if not compilers:
        raise AssertionError("no C compiler for actual-helper qualification")
    with tempfile.TemporaryDirectory(prefix="swapz-origin-commit-") as directory:
        source_path = Path(directory) / "actual-origin-commit.c"
        source_path.write_text(prelude + helper + exercise, encoding="utf-8")
        for compiler in compilers:
            output_path = Path(directory) / compiler
            compile_command = (
                compiler, "-std=gnu11", "-O2", "-Wall", "-Wextra", "-Werror",
                "-Wconversion", "-Wshadow", "-Wformat=2", "-Wstrict-prototypes",
                "-fsanitize=undefined", "-fno-sanitize-recover=all",
                str(source_path), "-o", str(output_path))
            compile_result = subprocess.run(
                compile_command, capture_output=True, text=True, timeout=30,
                check=False)
            if compile_result.returncode:
                raise AssertionError(
                    f"{compiler} actual helper compile exit={compile_result.returncode}: "
                    + compile_result.stderr[-1400:])
            execute_result = subprocess.run(
                (str(output_path),), capture_output=True, text=True,
                timeout=10, check=False)
            if execute_result.returncode:
                raise AssertionError(
                    f"{compiler} actual helper execute exit={execute_result.returncode}: "
                    + execute_result.stderr[-1400:])
            if "PASS exact production C helper" not in execute_result.stdout:
                raise AssertionError(f"{compiler} actual helper output missing")
    return len(compilers)


def main() -> int:
    source = SOURCE.read_text(encoding="utf-8")
    validate_source_text(source)
    verify_strict_phase_a_contract(source)
    verify_scoped_original_origin_mutations(source)
    legacy_detected = run_negative_mutations(source)
    typed_detected = run_typed_negative_mutations(source)
    scoped_detected = run_scoped_typed_negative_mutations(source)
    guarded_detected = run_guarded_fallback_negative_mutations(source)
    detected = legacy_detected + typed_detected + scoped_detected + guarded_detected
    print(f"PASS: legacy={legacy_detected} typed={typed_detected} scoped_typed={scoped_detected} mutation groups")
    print(f"PASS: guarded_fallback={guarded_detected} mutation groups")
    compiled = compile_actual_origin_commit_helper(source)
    print(f"PASS: real production-C Phase A source contract; {detected} negative mutations rejected")
    print(f"PASS: {compiled} real C compiler(s) exercised extracted guarded commit helper")
    print("Evidence class: rootless source-contract only; no genuine kernel writeback")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (AssertionError, OSError, ValueError) as failure:
        print(f"FAIL: {failure}", file=sys.stderr)
        raise SystemExit(1)
