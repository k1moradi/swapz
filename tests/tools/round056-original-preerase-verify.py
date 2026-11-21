#!/usr/bin/env python3
"""Round056 original pre-erase one-allocation guarded-C source verifier.

Hostile mutations are FUNCTION-SCOPED TEXTUAL CONTROLS, not compiled or
executed original kernel C. Actual KUnit boots/builds run separately in CI.
"""
from __future__ import annotations

import argparse
import importlib.util
from pathlib import Path
import re
import sys

HERE = Path(__file__).resolve().parent
COMPOSER = HERE / "stage-pinned-linux-zswap-composed.py"
spec = importlib.util.spec_from_file_location("round056_composer", COMPOSER)
if spec is None or spec.loader is None:
    raise RuntimeError("original_composer_loader_missing")
composer = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = composer
spec.loader.exec_module(composer)
source_module = composer.ROUND056

MM_SIGNATURE = "static __used noinline struct swapz_ci_owned_payload *\nswapz_round056_mm_bio_create("
BIO_SIGNATURE = "struct swapz_ci_owned_payload *\nswapz_round056_owned_reserve_source_v1("
SEAL_SIGNATURE = "bool swapz_round056_owned_seal_source_v1("
MOVE_SIGNATURE = "swapz_round056_mm_bio_create(entry, swpentry, tree, offset,"
NATIVE_SOURCE = "zswap_writeback_entry(struct zswap_entry *entry,"
AUDIT_MARKER = "ROUND056_STAGED_ORIGINAL_PREERASE_SOURCE_AUDIT_PASS"


class SourceAuditError(ValueError):
    pass


def body(source: str, signature: str) -> str:
    start = source.find(signature)
    if start < 0 or source.find(signature, start + len(signature)) >= 0:
        raise SourceAuditError("missing_or_repeated_C_signature:" + signature)
    opening = source.find("{", start)
    if opening < 0:
        raise SourceAuditError("missing_C_body:" + signature)
    depth = 0
    for index in range(opening, len(source)):
        character = source[index]
        if character == "{":
            depth += 1
        elif character == "}":
            depth -= 1
            if depth == 0:
                return source[start:index + 1]
    raise SourceAuditError("unbalanced_C_body:" + signature)


def ordered(fragment: str, *tokens: str) -> None:
    last = -1
    for token in tokens:
        position = fragment.find(token, last + 1)
        if position < 0:
            raise SourceAuditError("missing_or_wrong_order:" + token)
        last = position


def verify(mm: str, bio: str, *, staged: bool) -> None:
    mm_helper = body(mm, MM_SIGNATURE)
    bio_reserve = body(bio, BIO_SIGNATURE)
    bio_seal = body(bio, SEAL_SIGNATURE)
    for text, category in ((mm_helper, "mm"), (bio_reserve, "bio")):
        if any(marker in text for marker in (
                "folio_dup_swap(", "folio_put_swap(", "swap_put_entries_direct(",
                "bio_get(", "bio_endio(", "schedule_work(", "GFP_KERNEL")):
            raise SourceAuditError("forbidden_independent_owner_or_reclaim:" + category)
    ordered(mm_helper, "folio_test_locked(folio)",
            "folio_test_swapcache(folio)", "folio->swap.val != source_slot.val",
            "xa_load(tree, offset) != entry", 'strcmp(pool->tfm_name, "lz4")',
            'crypto_acomp_alg_driver_name(acomp_ctx->acomp)',
            "sha256(decoded, PAGE_SIZE, decoded_sha256)",
            "memcmp(decoded_sha256, entry->swapz_round028_store_sha256",
            "swapz_round028_slot_epoch(source_slot)",
            "swapz_round056_owned_reserve_source_v1(",
            "swapz_round056_owned_private_bytes(owner, length)",
            "zs_obj_read_sg_begin(", "memcpy_from_sglist(",
            "zs_obj_read_sg_end(", "entry != xa_load(tree, offset)",
            "swapz_round056_owned_seal_source_v1(owner)",
            "swapz_ci_owned_put(owner)", "memzero_explicit(decoded_sha256")
    ordered(bio_reserve, "compressed_length > SWAPZ_ROUND056_MAX_BYTES",
            "check_add_overflow(sizeof(*owner), compressed_length,",
            "atomic_add_unless(&swapz_round056_held_owners, 1,",
            "kzalloc(allocation_bytes, GFP_NOWAIT | __GFP_NOWARN)",
            "owner->swapz_round056_budgeted = true;",
            "refcount_set(&owner->references, 1);")
    ordered(bio_seal, "owner->swapz_round056_sealed",
            "refcount_read(&owner->references) != 1",
            "owner->compressed_crc32c =",
            "owner->swapz_round056_sealed = true",
            "swapz_ci_owned_valid(owner)")
    if "SWAPZ_ROUND056_MAX_OWNERS 4" not in bio or \
            "SWAPZ_ROUND056_MAX_BYTES 3568U" not in bio:
        raise SourceAuditError("bounded_budget_or_length_removed")
    if "if (owner && owner->swapz_round056_budgeted &&" not in bio or \
            "!owner->swapz_round056_sealed" not in bio:
        raise SourceAuditError("unsealed_owner_could_become_valid")
    if "kfree_sensitive(owner);" not in bio or \
            "atomic_dec(&swapz_round056_held_owners);" not in bio or \
            "if (budgeted)" not in bio:
        raise SourceAuditError("last_owner_unwind_missing")
    if "KUNIT_CASE(swapz_round034_v1_owned_copy_kunit)" not in bio or \
            "swapz_round056_owned_budget_kunit(test);" not in bio:
        if staged:
            raise SourceAuditError("real_original_registered_C_KUnit_not_exercising_budget")
    if staged:
        original_writeback = body(mm, NATIVE_SOURCE)
        ordered(original_writeback, "entry != xa_load(tree, offset)",
                "zswap_decompress(entry, folio)",
                MOVE_SIGNATURE, "xa_erase(tree, offset)",
                "zswap_entry_free(entry)", "__swap_writeout(&ctx, folio)",
                "swap_write_submit(&ctx)")
        # The older Round030 probe consumes the STORE-bound bit BEFORE
        # native decompression. It must not run in the new source producer
        # mode or the post-decode snapshot can never pass validation.
        protected_probe = (
            "#if !defined(SWAPZ_ROUND056_PREERASE_SINGLE_OWNER_TEST)\n"
            "\t(void)swapz_round030_snapshot_stored_lz4("
            "entry, swpentry, tree, offset);\n"
            "#endif\n")
        if protected_probe not in original_writeback:
            raise SourceAuditError("predecode_diagnostic_consumes_new_snapshot")
        if "swapz_round031_mm_bio_create(entry, swpentry, tree, offset)" not in original_writeback:
            raise SourceAuditError("inherited_snapshot_fallback_removed")
        if "ROUND056_ORIGINAL_MM_PREERASE_BEGIN" not in mm or \
                "ROUND056_ORIGINAL_BIO_BOUNDED_OWNER_BEGIN" not in bio:
            raise SourceAuditError("original_C_insertion_missing")
        for token in ("#if defined(" + source_module.MACRO,
                      "swapz_round056_owned_budget_kunit("):
            if token not in bio:
                raise SourceAuditError("test_only_bio_guard_missing:" + token)
        if "EXPORT_SYMBOL_GPL(swapz_round056" in bio or \
                "EXPORT_SYMBOL_GPL(swapz_round056" in mm:
            raise SourceAuditError("new_runtime_kernel_export_forbidden")


def verify_hostile_controls() -> int:
    mm = source_module.MM_C
    bio = (source_module.BIO_C +
           "\nSWAPZ_ROUND056_MAX_OWNERS 4\n"
           "SWAPZ_ROUND056_MAX_BYTES 3568U\n"
           "if (owner && owner->swapz_round056_budgeted &&\n"
           "    !owner->swapz_round056_sealed)\n"
           "kfree_sensitive(owner);\n"
           "if (budgeted)\n"
           "atomic_dec(&swapz_round056_held_owners);\n")
    verify(mm, bio, staged=False)
    changes = [
        ("mm", "folio_test_locked(folio)", "folio_test_lru(folio)"),
        ("mm", "entry != xa_load(tree, offset)", "entry == xa_load(tree, offset)"),
        ("mm", "crypto_acomp_alg_driver_name(acomp_ctx->acomp)",
         "crypto_acomp_alg_name(acomp_ctx->acomp)"),
        ("mm", "sha256(decoded, PAGE_SIZE, decoded_sha256)",
         "memcpy(decoded_sha256, decoded, 32U)"),
        ("mm", "memcpy_from_sglist(", "memcpy_from_sglist_broken("),
        ("bio", "atomic_add_unless(&swapz_round056_held_owners, 1,",
         "atomic_add_unless(&swapz_round056_held_owners, 2,"),
        ("bio", "kzalloc(allocation_bytes, GFP_NOWAIT | __GFP_NOWARN)",
         "kzalloc(allocation_bytes, GFP_KERNEL)"),
        ("bio", "owner->swapz_round056_sealed = true",
         "owner->swapz_round056_sealed = false"),
    ]
    for index, (target, old, new) in enumerate(changes):
        chosen = mm if target == "mm" else bio
        if chosen.count(old) != 1:
            raise SourceAuditError("bad_hostile_anchor:" + str(index))
        mutated = chosen.replace(old, new, 1)
        if mutated == chosen:
            raise SourceAuditError("empty_hostile_control:" + str(index))
        try:
            verify(mutated if target == "mm" else mm,
                   mutated if target == "bio" else bio, staged=False)
        except SourceAuditError:
            continue
        raise SourceAuditError("uncaught_function_scoped_control:" + str(index))
    return len(changes)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--linux-root", type=Path)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    try:
        hostile_count = verify_hostile_controls() if args.self_test else 0
        if args.linux_root is not None:
            root = args.linux_root.resolve(strict=True)
            mm = (root / "mm/zswap.c").read_text(encoding="utf-8")
            bio = (root / "block/bio.c").read_text(encoding="utf-8")
            verify(mm, bio, staged=True)
        elif not args.self_test:
            parser.error("use --self-test or --linux-root")
    except (SourceAuditError, OSError, UnicodeError) as error:
        print("ROUND056_ORIGINAL_PREERASE_SOURCE_BLOCKED first_error=" + str(error))
        return 2
    print(AUDIT_MARKER + " textual_function_hostiles=" + str(hostile_count)
          + " real_kernel_boot=SEPARATE original_mm_slot_count=NO"
          + " SOURCE_MAPPED_AUTHENTICATED=0 PHASE_A=BLOCKED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
