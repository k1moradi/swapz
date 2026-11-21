#!/usr/bin/env python3
"""Round060 pinned original zswap success-phase/BIO read-only source witness.

The observer cannot hold the original embedded swap_iocb or a borrowed DM
clone. This verifier inspects the actual staged original Linux source and
rejects a forged post-writeback/pre-decompression original-source success.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import runpy

HERE = Path(__file__).resolve().parent
FIXTURE_ROOT = HERE.parent / "runtime/native/fixtures"
SOURCE = FIXTURE_ROOT / "round058-original-stored-bio-chain.cfrag"
KUNIT = FIXTURE_ROOT / "round058-original-stored-bio-chain-kunit.cfrag"
PREVIOUS = HERE / "round059-original-source-lease-verify.py"


class FirstError(RuntimeError):
    """Precise fail-closed original source phase audit."""


# These are C expressions used in the real original block/bio.c function,
# not stand-in statuses. Their order matters for borrowed bvec validity.
SOURCE_LIFETIME_GATES = (
    "source_folio = page_folio(bio->bi_io_vec[0].bv_page);",
    "!folio_test_swapcache(source_folio)",
    "!folio_test_uptodate(source_folio)",
    "!folio_test_writeback(source_folio)",
    "folio_nr_pages(source_folio) != 1U",
    "owner = swapz_ci_owned_get(bio->bi_swapz_ci_sideband);",
    "owner->source_swap_entry != source_folio->swap.val",
    "sha256(original, 4096U, digest);",
    "swapz_ci_owned_put(owner);",
)

# This is the SAME native original 71-case suite, with added assertions.
KUNIT_PHASE_GATES = (
    "folio_mark_uptodate(source_folio);",
    "folio_lock(source_folio);",
    "folio_start_writeback(source_folio);",
    "folio_unlock(source_folio);",
    "folio_end_writeback_no_dropbehind(source_folio);",
    "folio_clear_uptodate(source_folio);",
    "folio_clear_swapcache(source_folio);",
    "KUNIT_EXPECT_NE(test, swapz_round058_source_bio_observe(&original_bio), 0);",
)


def check_fragment(source: str, kunit: str) -> None:
    positions = []
    for gate in SOURCE_LIFETIME_GATES:
        count = source.count(gate)
        if count != 1:
            raise FirstError(f"source_C_phase_gate_count:{gate}:{count}")
        positions.append(source.index(gate))
    if positions != sorted(positions):
        raise FirstError("source_C_phase_gate_order")
    # Do not confuse a C KUnit assertion repeated for several negative
    # scenarios with a new registered test. Existing 71 must remain 71.
    for gate in KUNIT_PHASE_GATES[:-1]:
        if gate not in kunit:
            raise FirstError("native_KUnit_original_phase_gate_missing:" + gate)
    if kunit.count(KUNIT_PHASE_GATES[-1]) < 3:
        raise FirstError("native_KUnit_missing_phase_rejection_assertions")
    if kunit.count("KUNIT_CASE(swapz_round058_original_stored_bio_chain_kunit)") != 1:
        raise FirstError("native_KUnit_case_count_changed")
    if "SOURCE_MAPPED_AUTHENTICATED=1" in source or "bio_get(bio)" in source:
        raise FirstError("invalid_source_positive_DM_lease")


def check_staged(root: Path) -> None:
    # Preserve all 17 previous source-only restrictions independently,
    # including real native DM clone_bvec lifetime and 71 registered cases.
    old = runpy.run_path(str(PREVIOUS), run_name="round060_previous_original_source")
    old["check_staged"](root)

    source = SOURCE.read_text(encoding="utf-8")
    kunit = KUNIT.read_text(encoding="utf-8")
    check_fragment(source, kunit)

    def original(path: str) -> str:
        return (root / path).read_text(encoding="utf-8")

    block = original("block/bio.c")
    mm = original("mm/zswap.c")
    page = original("mm/page_io.c")
    if block.count(source.strip()) != 1 or block.count(kunit.strip()) != 1:
        raise FirstError("staged_original_block_BIO_C_or_KUnit_postimage_drift")

    producer = old["enclosed_function"](mm, "static int zswap_writeback_entry(")
    writeout = old["enclosed_function"](page, "void __swap_writeout(")
    submit = old["enclosed_function"](page, "static void swap_bdev_submit_write(")
    native_stored = (
        producer.find("zswap_decompress(entry, folio)"),
        producer.find("xa_erase(tree, offset)"),
        producer.find("folio_mark_uptodate(folio);"),
        producer.find("__swap_writeout(&ctx, folio);"),
        producer.find("swap_write_submit(&ctx);"),
    )
    if -1 in native_stored or list(native_stored) != sorted(native_stored):
        raise FirstError("genuine_zswap_successful_decompress_uptodate_submit_order")
    native_writeout = (
        writeout.find("folio_start_writeback(folio);"),
        writeout.find("folio_unlock(folio);"),
        writeout.find("swap_add_folio(ctx, folio, WRITE);"),
    )
    if -1 in native_writeout or list(native_writeout) != sorted(native_writeout):
        raise FirstError("genuine_swapcache_writeback_before_BIO_submit_order")
    native_submit = (
        submit.find("bio_init(bio, ctx->sis->bdev"),
        submit.find("bio->bi_iter.bi_sector = swap_folio_sector"),
        submit.find("(void)swapz_round058_source_bio_observe(bio);"),
        submit.find("submit_bio(bio);"),
    )
    if -1 in native_submit or list(native_submit) != sorted(native_submit):
        raise FirstError("genuine_original_BIO_pre_submit_phase_witness_order")
    # The kernel may complete the original embedded BIO only at real endio,
    # after which neither this source test nor current DM may borrow bvec.
    if "bio_uninit(bio);\n\tswap_write_end(sio, failed);" not in page:
        raise FirstError("native_endio_borrowed_original_bvec_owner_destroy")
    print("ROUND060_PINNED_ORIGINAL_STORED_UPTODATE_WRITEBACK_PHASE_STAGED_PASS "
          "native_KUnit_cases=71 AUTH0 DM_LEASE=NOT_PROVEN")


def self_test() -> None:
    source = SOURCE.read_text(encoding="utf-8")
    kunit = KUNIT.read_text(encoding="utf-8")
    check_fragment(source, kunit)
    rejected = 0
    for gate in SOURCE_LIFETIME_GATES:
        changed = source.replace(gate, "false /* hostile changed original C */", 1)
        try:
            check_fragment(changed, kunit)
        except FirstError:
            rejected += 1
        else:
            raise FirstError("original_source_phase_mutant_accepted:" + gate)
    print(f"ROUND060_PINNED_SOURCE_PHASE_{rejected}_CHANGED_C_AUDITS_PASS "
          "compiled_executable_semantic_mutants=SEPARATE AUTH0")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("self-test", "staged"))
    parser.add_argument("--linux-root", type=Path)
    args = parser.parse_args()
    try:
        if args.mode == "self-test":
            self_test()
        else:
            if args.linux_root is None:
                parser.error("staged requires --linux-root")
            check_staged(args.linux_root.resolve(strict=True))
    except (OSError, ValueError, RuntimeError) as error:
        print("ROUND060_ORIGINAL_SOURCE_FIRST_ERROR phase=source_BIO_owner "
              "reason=" + str(error))
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
