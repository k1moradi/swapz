#!/usr/bin/env python3
"""Independent Round059 original Linux source owner/slot/BIO lifetime audit.

Read-only check of the genuine composed pinned Linux C postimage. Successful
source matching is never a current DM-table/BIO lease or production authority.
"""
from __future__ import annotations

import argparse
from pathlib import Path

HERE = Path(__file__).resolve().parent
FIXTURE = HERE.parent / "runtime/native/fixtures/round058-original-stored-bio-chain.cfrag"


class FirstError(RuntimeError):
    """Precise original-source contract failure; no false positive AUTH."""


# Deliberately anchored in the actual guarded C, not a synthetic token model.
SOURCE_GATES = (
    "bio->bi_swap_origin != SWAP_BIO_ORIGIN_ZSWAP_STORED_WRITEBACK",
    "(bio->bi_flags & (1U << BIO_CLONED))",
    "bio->bi_iter.bi_size != 4096U",
    "bio->bi_iter.bi_sector < 8U",
    "bio->bi_iter.bi_sector % 8U",
    "bio->bi_vcnt || !bio->bi_io_vec",
    "source_folio = page_folio(bio->bi_io_vec[0].bv_page);",
    "!folio_test_swapcache(source_folio)",
    "folio_nr_pages(source_folio) != 1U",
    "owner->source_swap_entry != source_folio->swap.val",
    "owner->swapz_round056_budgeted",
    "owner->swapz_round056_sealed",
    "swapz_ci_owned_valid(owner)",
    "sha256(original, 4096U, digest);",
    "!memcmp(digest, owner->original_sha256, sizeof(digest))",
    "memzero_explicit(digest, sizeof(digest));",
    "swapz_ci_owned_put(owner);",
)


def check_fragment(source: str) -> None:
    for gate in SOURCE_GATES:
        if source.count(gate) != 1:
            raise FirstError("source_gate_missing_or_duplicated:" + gate)
    first = source.index("bio->bi_vcnt || !bio->bi_io_vec")
    folio = source.index("source_folio = page_folio")
    ref = source.index("owner = swapz_ci_owned_get")
    slot = source.index("owner->source_swap_entry != source_folio->swap.val")
    digest = source.index("sha256(original, 4096U, digest)")
    release = source.index("swapz_ci_owned_put(owner);")
    if not first < folio < ref < slot < digest < release:
        raise FirstError("source_owner_pre_submit_lifetime_order_drift")
    # None of the source checks may be allowed to claim target ownership.
    if "SOURCE_MAPPED_AUTHENTICATED=1" in source or "bio_get(bio)" in source:
        raise FirstError("source_positive_authority_or_embedded_bio_get")


def enclosed_function(text: str, signature: str) -> str:
    start = text.find(signature)
    if start < 0:
        raise FirstError("original_function_missing:" + signature)
    end = text.find("\n}\n", start)
    if end < 0:
        raise FirstError("original_function_unterminated:" + signature)
    return text[start:end + 3]


def check_staged(root: Path) -> None:
    def read(path: str) -> str:
        return (root / path).read_text(encoding="utf-8")

    mm = read("mm/zswap.c")
    page = read("mm/page_io.c")
    bio = read("block/bio.c")
    header = read("include/linux/bio.h")
    original_block = read("drivers/md/dm.c")
    fragment = FIXTURE.read_text(encoding="utf-8")
    check_fragment(fragment)
    if bio.count(fragment.strip()) != 1:
        raise FirstError("source_original_block_bio_not_identical_to_fixture")
    producer = enclosed_function(mm, "static int zswap_writeback_entry(")
    ordered = (
        "xa_load(tree, offset)",
        "zswap_decompress(entry, folio)",
        "swapz_round056_mm_bio_create(entry, swpentry, tree, offset,",
        "xa_erase(tree, offset)",
        "zswap_entry_free(entry)",
    )
    offsets = [producer.find(item) for item in ordered]
    if any(position < 0 for position in offsets) or offsets != sorted(offsets) or len(set(offsets)) != len(offsets):
        raise FirstError("original_STORED_decompress_capture_erase_lifetime_order")
    for gate in ('strcmp(crypto_acomp_alg_name(acomp_ctx->acomp), "lz4")',
                 'strcmp(crypto_acomp_driver_name(acomp_ctx->acomp), "lz4-scomp")',
                 "folio->swap.val != source_slot.val",
                 "xa_load(tree, offset) != entry",
                 "slot_epoch(source_slot)"):
        if gate not in mm:
            raise FirstError("original_selected_codec_or_slot_epoch_missing:" + gate)
    submit = enclosed_function(page, "static void swap_bdev_submit_write(")
    offsets = [submit.find(item) for item in (
        "bio_init(bio, ctx->sis->bdev",
        "bio->bi_swapz_ci_sideband = ctx->swapz_round031_owned;",
        "bio->bi_iter.bi_sector = swap_folio_sector",
        "(void)swapz_round058_source_bio_observe(bio);",
        "submit_bio(bio);")]
    if any(position < 0 for position in offsets) or offsets != sorted(offsets) or len(set(offsets)) != len(offsets):
        raise FirstError("original_source_bio_native_submit_order")
    if "folio_start_writeback(folio);\n\tfolio_unlock(folio);" not in page or \
       "bio_uninit(bio);\n\tswap_write_end(sio, failed);" not in page:
        raise FirstError("original_bvec_owner_writeback_endio_missing")
    if "int swapz_round058_source_bio_observe(const struct bio *bio);" not in header or \
       "source->bi_vcnt != 1U" not in bio or \
       "clone->bi_round056_candidate = false;" not in original_block:
        raise FirstError("original_parent_clone_ticket_cannot_own_current_target")
    if "bio_alloc_clone(NULL, bio, gfp_mask, &md->mempools->io_bs);" not in original_block:
        raise FirstError("original_DM_real_cloned_borrowed_bvec_path_missing")
    if "kunit_test_suite(swapz_round058_original_chain_suite);" not in bio or \
       "source_folio->swap.val = 14U;" not in bio or \
       "folio_clear_swapcache(source_folio);" not in bio:
        raise FirstError("original_inherited71_case_slot_negative_missing")
    print("ROUND059_ORIGINAL_PINNED_COMPOSED_MM_BIO_DM_SOURCE_ORDER_PASS "
          "native_cases=71 AUTH0 DM_SOURCE_OWNER=NOT_PROVEN")


def self_test() -> None:
    source = FIXTURE.read_text(encoding="utf-8")
    check_fragment(source)
    rejected = 0
    for gate in SOURCE_GATES:
        hostile = source.replace(gate, "false /* Round059 hostile changed original C */", 1)
        try:
            check_fragment(hostile)
        except FirstError:
            rejected += 1
        else:
            raise FirstError("changed_original_C_source_gate_accepted:" + gate)
    # A textual verdict never proves the actual checked source was executed.
    print(f"ROUND059_SOURCE_GATES_ORIGINAL_C_{rejected}_NEGATIVE_AUDITS_PASS "
          "semantic_binary_mutants=SEPARATE AUTH0")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("staged", "self-test"))
    parser.add_argument("--linux-root", type=Path)
    opts = parser.parse_args()
    try:
        if opts.mode == "staged":
            if opts.linux_root is None:
                parser.error("staged requires --linux-root")
            check_staged(opts.linux_root.resolve(strict=True))
        else:
            self_test()
    except (FirstError, OSError, ValueError) as error:
        print("ROUND059_ORIGINAL_FIRST_ERROR phase=source_lifetime reason=" + str(error))
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
