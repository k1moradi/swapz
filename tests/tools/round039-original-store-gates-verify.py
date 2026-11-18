#!/usr/bin/env python3
"""Round039 fail-closed original source gate verifier: distinct 037 MM and 038 STORE.

This checks repository workflow *source* and the original pinned Linux composer.
It cannot substitute for genuine original booted 36-case JSON+KTAP or full
original x86 vmlinux/modules/GPL probe/same-kernel dm-swapz.ko verification.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github/workflows/phase-a-zswap-original-store-bio-provenance.yml"
COMPOSER = ROOT / "tests/tools/stage-pinned-linux-zswap-composed.py"

# These checks guard both source composition and actual gated ELF machine code.
# Original Round037 MM/page_io owns scoped swap area refs. Original Round038
# mm/zswap owns new STORE SHA/CRC diagnostic and original-C KUnit suite.
REQUIRED_WORKFLOW = (
    "grep -Fq 'swapz_round037_original_mm_scoped_probe(' linux/mm/page_io.c",
    "grep -Fq 'kunit_test_suite(swapz_round037_scope_suite);' linux/mm/page_io.c",
    'nm -a "$out/mm/page_io.o" | grep -q swapz_round037_original_mm_scoped_probe',
    "grep -Fq 'get_swap_device(original_slot)' linux/mm/page_io.c",
    "grep -Fq 'put_swap_device(active_area)' linux/mm/page_io.c",
    "grep -Fq 'swap_folio_sector(folio)' linux/mm/page_io.c",
    "grep -Fq 'swapz_round038_actual_store_provenance_probe(' linux/mm/zswap.c",
    "grep -Fq 'swapz_round038_store_crc32c = ~crc32c(' linux/mm/zswap.c",
    "grep -Fq 'entry->swapz_round038_store_crc32c == source_crc32c' linux/mm/zswap.c",
    "grep -Fq 'kunit_test_suite(swapz_round038_store_suite);' linux/mm/zswap.c",
    "grep -Fq '\"swapz_round038_original_store_provenance_no_authority\"' linux/mm/zswap.c",
    'nm -a "$out/mm/zswap.o" | grep -q swapz_round038_actual_store_provenance_probe',
    'nm -a "$out/mm/zswap.o" | grep -q swapz_round038_store_observation_check',
    "-DSWAPZ_ROUND037_ORIGINAL_MM_LIFETIME_OWNER_TEST=1",
    "-DSWAPZ_ROUND038_ORIGINAL_STORE_PROVENANCE_TEST=1",
    "round038-original-store-provenance-verify.py",
    "executed_total=36",
    "Module.symvers",
    "round032-bio-probe.ko",
    "dm-swapz.ko",
)
REQUIRED_COMPOSER = (
    'ROUND037_MM_OWNER_MACRO = "SWAPZ_ROUND037_ORIGINAL_MM_LIFETIME_OWNER_TEST"',
    'ROUND038_STORE_PROVENANCE_MACRO = "SWAPZ_ROUND038_ORIGINAL_STORE_PROVENANCE_TEST"',
    "static noinline int swapz_round037_original_mm_scoped_probe(",
    "kunit_test_suite(swapz_round037_scope_suite);",
    "static noinline int swapz_round038_actual_store_provenance_probe(",
    "kunit_test_suite(swapz_round038_store_suite);",
    '.name = "swapz_round038_original_store_provenance_no_authority"',
    "entry->swapz_round038_store_crc32c == source_crc32c",
    "swapz_round028_slot_epoch(original_slot)",
    "return -EOPNOTSUPP;",
)


class OriginalGateEvidenceError(ValueError):
    """A copied, absent, misplaced or renamed original C witness blocks CI."""


def verify(workflow: str, composer: str) -> None:
    for forbidden in (
        "swapz_round038_original_mm_scoped_probe",
        "swapz_round038_scope_suite",
    ):
        if forbidden in workflow:
            raise OriginalGateEvidenceError("stale_pageio_symbol:" + forbidden)
    for required in REQUIRED_WORKFLOW:
        if required not in workflow:
            raise OriginalGateEvidenceError("missing_original_workflow_gate:" + required)
    for required in REQUIRED_COMPOSER:
        if required not in composer:
            raise OriginalGateEvidenceError("missing_actual_original_source:" + required)
    # No live source admission or original hardware/source spoofing.
    if "SOURCE_MAPPED_AUTHENTICATED=1" in workflow:
        raise OriginalGateEvidenceError("forbidden_live_source_admission")


def read_bounded(path: Path) -> str:
    if path.is_symlink() or not path.is_file() or not 0 < path.stat().st_size < 300_000:
        raise OriginalGateEvidenceError("missing_or_oversized_source")
    return path.read_text(encoding="utf-8")


class HostileGateSelfTest(unittest.TestCase):
    def test_real_current_original_workflow_and_composer(self):
        verify(read_bounded(WORKFLOW), read_bounded(COMPOSER))

    def test_stale_copied_pageio_probe_is_rejected(self):
        original = read_bounded(WORKFLOW)
        wrong = original.replace(
            "swapz_round037_original_mm_scoped_probe",
            "swapz_round038_original_mm_scoped_probe",
        )
        with self.assertRaisesRegex(OriginalGateEvidenceError, "stale_pageio_symbol"):
            verify(wrong, read_bounded(COMPOSER))

    def test_stale_copied_pageio_suite_is_rejected(self):
        original = read_bounded(WORKFLOW)
        wrong = original.replace(
            "kunit_test_suite(swapz_round037_scope_suite);",
            "kunit_test_suite(swapz_round038_scope_suite);",
        )
        with self.assertRaisesRegex(OriginalGateEvidenceError, "stale_pageio_symbol"):
            verify(wrong, read_bounded(COMPOSER))

    def test_missing_real_store_suite_or_original_elf_gate_is_rejected(self):
        original = read_bounded(WORKFLOW)
        for exact in (
            "kunit_test_suite(swapz_round038_store_suite);",
            'nm -a "$out/mm/zswap.o" | grep -q swapz_round038_actual_store_provenance_probe',
            "executed_total=36",
        ):
            with self.subTest(exact=exact):
                with self.assertRaisesRegex(
                    OriginalGateEvidenceError, "missing_original_workflow_gate"
                ):
                    verify(original.replace(exact, "NONEXISTENT_ORIGINAL_GATE"),
                           read_bounded(COMPOSER))

    def test_original_composer_symbols_and_live_refusal_are_mandatory(self):
        workflow = read_bounded(WORKFLOW)
        original = read_bounded(COMPOSER)
        for exact in (
            "static noinline int swapz_round037_original_mm_scoped_probe(",
            "kunit_test_suite(swapz_round038_store_suite);",
            "return -EOPNOTSUPP;",
        ):
            with self.subTest(exact=exact):
                with self.assertRaisesRegex(
                    OriginalGateEvidenceError, "missing_actual_original_source"
                ):
                    verify(workflow, original.replace(exact, "REMOVED_ORIGINAL_C"))
        with self.assertRaisesRegex(OriginalGateEvidenceError, "forbidden_live"):
            verify(workflow + "\nSOURCE_MAPPED_AUTHENTICATED=1", original)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        results = unittest.TextTestRunner(verbosity=2).run(
            unittest.defaultTestLoader.loadTestsFromTestCase(HostileGateSelfTest)
        )
        if not results.wasSuccessful():
            return 1
    else:
        verify(read_bounded(WORKFLOW), read_bounded(COMPOSER))
    print("ROUND039_ORIGINAL_037_MM_038_STORE_SEPARATE_SOURCE_GATE_PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
