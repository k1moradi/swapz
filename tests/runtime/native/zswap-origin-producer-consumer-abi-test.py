#!/usr/bin/env python3
"""Rootless, source-bound pinned Linux producer to swapz BIO origin ABI checks.

This checks committed upstream edit anchors and production DM C. Extracted C
predicates are not full Linux KUnit, loaded ABI, or real writeback evidence.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[3]
STAGER = ROOT / "tests/tools/stage-pinned-linux-zswap-origin.py"
CONSUMER_TEST = ROOT / "tests/runtime/native/zswap-origin-consumer-source-test.py"
STAGE_TEST = ROOT / "tests/runtime/native/pinned-linux-zswap-origin-stage-test.py"
SOURCE = ROOT / "src/kernel/dm-target.c"
PINNED_LINUX_SHA = "c339f4010dea8b0d754f84ace70cd1b089878ef8"


def load_module(path: Path, module_name: str):
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise AssertionError("required frozen source module unavailable: " + module_name)
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


stager = load_module(STAGER, "round011_pinned_stager")
consumer_test = load_module(CONSUMER_TEST, "round011_consumer_contract")
stager_test = load_module(STAGE_TEST, "round011_staging_test")


def require(condition: bool, label: str) -> None:
    if not condition:
        raise AssertionError(label)


def source_postimages() -> dict[str, str]:
    """Use the real staging code and its byte-exact pinned upstream anchors.

    These are original-anchor excerpts; full upstream postimage and Git-blob
    identity remain the separate staging preflight/Kbuild qualification.
    """
    require(stager.LINUX_COMMIT == PINNED_LINUX_SHA, "Linux source SHA")
    require(set(stager.EDITS) == set(stager.ORIGINAL_BLOBS) - {"Makefile"},
            "six-file pinned allowlist")
    require(sum(len(edits) for edits in stager.EDITS.values()) == 13,
            "thirteen frozen source transformations")
    result = {}
    for path, edits in stager.EDITS.items():
        original = "\n\n/* original upstream anchor boundary */\n\n".join(
            edit.before for edit in edits)
        result[path] = stager.render_source(path, original)
        for edit in edits:
            require(edit.after in result[path] and edit.before not in result[path],
                    "changed source staging output: " + path)
    return result


def validate_staged(postimages: dict[str, str]) -> None:
    require(set(postimages) == set(stager.EDITS), "incomplete producer source set")
    for path, edits in stager.EDITS.items():
        stager.validate_origin_postimage(path, postimages[path])
        for edit in edits:
            require(edit.after in postimages[path] and edit.before not in postimages[path],
                    "staged C transition mismatches frozen edit: " + path)
    types = postimages["include/linux/blk_types.h"]
    header = postimages["include/linux/bio.h"]
    block = postimages["block/bio.c"]
    page = postimages["mm/page_io.c"]
    zswap = postimages["mm/zswap.c"]
    require(types.count("SWAP_BIO_ORIGIN_ORDINARY_OR_UNKNOWN = 0,") == 1 and
            types.count("SWAP_BIO_ORIGIN_ZSWAP_STORED_WRITEBACK = 1,") == 1,
            "producer unknown-zero and authenticated-positive enum")
    require(header.count("#define BIO_HAS_ZSWAP_STORED_WRITEBACK_ORIGIN 1") == 1 and
            "bio_op(bio) == REQ_OP_WRITE &&" in header and
            "(bio->bi_opf & REQ_SWAP) &&" in header and
            "bio->bi_swap_origin == SWAP_BIO_ORIGIN_ZSWAP_STORED_WRITEBACK;" in header,
            "BIO helper must authenticate WRITE/REQ_SWAP/stored tag")
    require("bio->bi_swap_origin = SWAP_BIO_ORIGIN_ORDINARY_OR_UNKNOWN;" in block and
            "bio->bi_swap_origin = bio_is_zswap_stored_writeback(bio_src) ?" in block and
            "bio->bi_swap_origin = bio_src->bi_swap_origin;" not in block,
            "recycled BIO reset and clone must not forge provenance")
    require("rw == WRITE &&\n\t    !swap_bio_origin_can_merge(ctx->sio->swap_origin, ctx->swap_origin)" in page and
            "sio->swap_origin = rw == WRITE &&" in page and
            "bio->bi_swap_origin = sio->swap_origin;" in page,
            "only homogeneous WRITE contexts propagate positive origin")
    require(postimages["include/linux/swap_ops.h"].count(
            "enum swap_bio_origin\tswap_origin;") == 2,
            "both swap context owners must carry origin")
    producer = "ctx.swap_origin = SWAP_BIO_ORIGIN_ZSWAP_STORED_WRITEBACK;"
    require(zswap.count(producer) == 1 and
            zswap.index("folio_set_dropbehind(folio);") < zswap.index(producer) <
            zswap.index("Drop our reference before starting writeback"),
            "stored-entry positive must follow successful decompression boundary")
    require("REQ_ZSWAP_WRITEBACK" not in "".join(postimages.values()),
            "no invented shortcut source")


def validate_consumer(source: str) -> None:
    consumer_test.validate_source_text(source)
    consumer_test.verify_strict_phase_a_contract(source)
    require('#error "swapz requires 4KiB PAGE_SIZE"' in source and
            '#define SWAPZ_SECTORS (SWAPZ_BLOCK_BYTES >> SECTOR_SHIFT)' in source,
            "fixed 4KiB / 512-byte-sector consumer geometry")
    gate = ("entry->write_origin = SWAPZ_WRITE_ORIGIN_ORDINARY_OR_UNKNOWN;\n"
            "#ifdef BIO_HAS_ZSWAP_STORED_WRITEBACK_ORIGIN\n"
            "\tif (bio_op(bio) == REQ_OP_WRITE && count == SWAPZ_SECTORS &&\n"
            "\t    bio->bi_iter.bi_size == SWAPZ_BLOCK_BYTES &&\n"
            "\t    bio_is_zswap_stored_writeback(bio))\n"
            "\t\tentry->write_origin = SWAPZ_WRITE_ORIGIN_ZSWAP_STORED_WRITEBACK;\n"
            "#endif")
    require(source.count(gate) == 1, "guarded 4096-byte READ/WRITE classification")
    require("raw_committed_verified_origin_bypass" not in source,
            "Phase B RAW scheduling must stay disabled")
    # The existing consumer contract also verifies the four foreground
    # representation success hooks, including RAW and zero authority.


def change_one(original: str, before: str, after: str) -> str:
    require(original.count(before) == 1 and before != after,
            "negative mutation has an ambiguous or inert source anchor")
    return original.replace(before, after, 1)


PRODUCER_NEGATIVES = (
    ("promoted default", "include/linux/blk_types.h", "SWAP_BIO_ORIGIN_ORDINARY_OR_UNKNOWN = 0,", "SWAP_BIO_ORIGIN_ORDINARY_OR_UNKNOWN = 1,"),
    ("false positive zero", "include/linux/blk_types.h", "SWAP_BIO_ORIGIN_ZSWAP_STORED_WRITEBACK = 1,", "SWAP_BIO_ORIGIN_ZSWAP_STORED_WRITEBACK = 0,"),
    ("missing BIO member", "include/linux/blk_types.h", "bi_swap_origin; /* scalar source, never encoding */", "bi_wrong_origin;"),
    ("missing helper feature macro", "include/linux/bio.h", "#define BIO_HAS_ZSWAP_STORED_WRITEBACK_ORIGIN 1", "/* no feature */"),
    ("READ helper accepted", "include/linux/bio.h", "bio_op(bio) == REQ_OP_WRITE &&", "bio_op(bio) == REQ_OP_READ &&"),
    ("REQ_SWAP omitted", "include/linux/bio.h", "(bio->bi_opf & REQ_SWAP) &&", "true &&"),
    ("helper forged positive", "include/linux/bio.h", "bio->bi_swap_origin == SWAP_BIO_ORIGIN_ZSWAP_STORED_WRITEBACK;", "true;"),
    ("recycled BIO promoted", "block/bio.c", "bio->bi_swap_origin = SWAP_BIO_ORIGIN_ORDINARY_OR_UNKNOWN;", "bio->bi_swap_origin = SWAP_BIO_ORIGIN_ZSWAP_STORED_WRITEBACK;"),
    ("clone raw scalar", "block/bio.c", "bio_is_zswap_stored_writeback(bio_src) ?", "bio_src->bi_swap_origin ?"),
    ("clone unconditional positive", "block/bio.c", "\t\tSWAP_BIO_ORIGIN_ZSWAP_STORED_WRITEBACK :\n\t\tSWAP_BIO_ORIGIN_ORDINARY_OR_UNKNOWN;", "\t\tSWAP_BIO_ORIGIN_ZSWAP_STORED_WRITEBACK :\n\t\tSWAP_BIO_ORIGIN_ZSWAP_STORED_WRITEBACK;"),
    ("lost context owner", "include/linux/swap_ops.h", "len;\n\tenum swap_bio_origin\tswap_origin;", "len;\n\tunsigned int unused_origin;"),
    ("mixed-origin merge", "mm/page_io.c", "!swap_bio_origin_can_merge(ctx->sio->swap_origin, ctx->swap_origin)", "swap_bio_origin_can_merge(ctx->sio->swap_origin, ctx->swap_origin)"),
    ("missing origin merge fence", "mm/page_io.c", "rw == WRITE &&\n\t    !swap_bio_origin_can_merge(ctx->sio->swap_origin, ctx->swap_origin)", "rw == WRITE &&\n\t    false"),
    ("READ origin propagation", "mm/page_io.c", "sio->swap_origin = rw == WRITE &&", "sio->swap_origin = true &&"),
    ("drop BIO origin transfer", "mm/page_io.c", "bio->bi_swap_origin = sio->swap_origin;", "bio->bi_swap_origin = SWAP_BIO_ORIGIN_ORDINARY_OR_UNKNOWN;"),
    ("forged scalar transfer", "mm/page_io.c", "bio->bi_swap_origin = sio->swap_origin;", "bio->bi_swap_origin = SWAP_BIO_ORIGIN_ZSWAP_STORED_WRITEBACK;"),
    ("zswap attribution missing", "mm/zswap.c", "ctx.swap_origin = SWAP_BIO_ORIGIN_ZSWAP_STORED_WRITEBACK;", "ctx.swap_origin = SWAP_BIO_ORIGIN_ORDINARY_OR_UNKNOWN;"),
    ("missing BIO reset", "block/bio.c", "bio->bi_swap_origin = SWAP_BIO_ORIGIN_ORDINARY_OR_UNKNOWN;", "/* origin reset removed */"),
    ("lost second context", "include/linux/swap_ops.h", "/* Zero initialized for every ordinary or rejected swap page. */\n\tenum swap_bio_origin\tswap_origin;", "/* context provenance removed */"),
    ("mixed-origin merge via OR", "mm/page_io.c", "rw == WRITE &&\n\t    !swap_bio_origin_can_merge(ctx->sio->swap_origin, ctx->swap_origin)", "rw == WRITE ||\n\t    !swap_bio_origin_can_merge(ctx->sio->swap_origin, ctx->swap_origin)"),
    ("unverified producer positive", "mm/zswap.c", "ctx.swap_origin = SWAP_BIO_ORIGIN_ZSWAP_STORED_WRITEBACK;", "ctx.swap_origin = SWAP_BIO_ORIGIN_ZSWAP_STORED_WRITEBACK | 1;"),
    ("zswap assignment too early", "mm/zswap.c", "folio_set_dropbehind(folio);\n\t/* Entry identity was checked and decompression succeeded. */\n\tctx.swap_origin = SWAP_BIO_ORIGIN_ZSWAP_STORED_WRITEBACK;", "ctx.swap_origin = SWAP_BIO_ORIGIN_ZSWAP_STORED_WRITEBACK;\n\tfolio_set_dropbehind(folio);"),
)


class PinnedProducerConsumerTests(unittest.TestCase):
    def test_real_source_contract_and_existing_foreground_hooks(self):
        validate_staged(source_postimages())
        validate_consumer(SOURCE.read_text(encoding="utf-8"))

    def test_deliberate_source_mutation_refusals(self):
        original = source_postimages()
        validate_staged(original)
        detected = 0
        for name, path, before, after in PRODUCER_NEGATIVES:
            with self.subTest(mutation=name):
                changed = dict(original)
                changed[path] = change_one(original[path], before, after)
                with self.assertRaises((AssertionError, stager.StagingError)):
                    validate_staged(changed)
                detected += 1
        # Existing source-controlled production regression adds 20 independent
        # map/admission/commit/codec mutants to the same rootless run.
        consumer = SOURCE.read_text(encoding="utf-8")
        validate_consumer(consumer)
        detected += consumer_test.run_negative_mutations(consumer)
        self.assertGreaterEqual(detected, 20)
        print(f"PASS: {detected} producer and consumer mutations rejected")

    def test_compiled_real_bio_predicate_and_clone(self):
        # Reuse the existing actual staged C predicate/clone test; it runs
        # GCC and Clang with UBSan and does not simulate a kernel runtime.
        test = stager_test.PinnedLinuxStageTests("test_pinned_cloned_origin_c_fixture")
        result = unittest.TestResult()
        test.run(result)
        if result.skipped:
            self.skipTest("no C compiler available")
        self.assertEqual(result.errors, [])
        self.assertEqual(result.failures, [])
        self.assertEqual(result.testsRun, 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
