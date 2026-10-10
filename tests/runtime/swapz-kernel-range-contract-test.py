#!/usr/bin/env python3
"""Rootless production-C range guards and fail-closed call-order contracts.

Compiles ONLY two pure guard functions extracted verbatim from dm-swapz.c
into an ordinary userspace shared object. Never builds/loads a kernel module,
opens block devices, changes swap, or grants cleanup authority.
"""

from __future__ import annotations

import ctypes
import errno
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
KERNEL = ROOT / "kernel" / "dm-swapz.c"
BLOCK_SECTORS = 8
U32_MAX = (1 << 32) - 1
U64_MAX = (1 << 64) - 1


def extract_function(source: str, name: str) -> str:
    """Extract one brace-balanced C function, rejecting a missing definition."""
    found = list(re.finditer(
        r"\bstatic\s+(?:int|void)\s+" + re.escape(name) +
        r"\s*\([^;{}]*\)\s*\{", source, re.DOTALL,
    ))
    if len(found) != 1:
        raise AssertionError(f"missing or repeated production C function: {name}")
    start = found[0].start()
    position = found[0].end() - 1
    depth = 0
    # Targeted source has ordinary C blocks; fail closed on malformed braces.
    for index in range(position, len(source)):
        char = source[index]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return source[start:index + 1]
    raise AssertionError(f"unterminated production C function: {name}")


def compile_source(source: str, folder: Path) -> ctypes.CDLL:
    cc = shutil.which("cc")
    if cc is None:
        raise AssertionError("C compiler required for exact production-guard qualification")
    page = extract_function(source, "swapz_checked_page_index")
    discard = extract_function(source, "swapz_checked_discard_range")
    harness = """
#include <stdint.h>
#include <errno.h>
typedef uint32_t u32;
typedef uint64_t sector_t;
#define SWAPZ_BLOCK_SECTORS 8ULL
""" + page + "\n" + discard + """
int audit_page(uint32_t limit, uint64_t sector, uint32_t *page) {
    return swapz_checked_page_index(limit, sector, page);
}
int audit_discard(uint32_t limit, uint64_t sector, uint64_t sectors) {
    return swapz_checked_discard_range(limit, sector, sectors);
}
"""
    source_file = folder / "exact-production-guards.c"
    output = folder / "exact-production-guards.so"
    source_file.write_text(harness, encoding="utf-8")
    process = subprocess.run(
        [cc, "-std=c11", "-O2", "-Wall", "-Wextra", "-Werror",
         "-fPIC", "-shared", "-o", str(output), str(source_file)],
        capture_output=True, text=True, check=False, timeout=15,
    )
    if process.returncode:
        raise AssertionError(f"production C guard did not compile: {process.stderr}")
    lib = ctypes.CDLL(str(output))
    lib.audit_page.argtypes = (ctypes.c_uint32, ctypes.c_uint64,
                               ctypes.POINTER(ctypes.c_uint32))
    lib.audit_page.restype = ctypes.c_int
    lib.audit_discard.argtypes = (ctypes.c_uint32, ctypes.c_uint64,
                                  ctypes.c_uint64)
    lib.audit_discard.restype = ctypes.c_int
    return lib


class ExactKernelRangeContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = KERNEL.read_text(encoding="utf-8")
        cls.temp = tempfile.TemporaryDirectory(prefix="swapz-kernel-ranges-")
        cls.lib = compile_source(cls.source, Path(cls.temp.name))

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def page(self, limit: int, sector: int):
        target = ctypes.c_uint32(0xDEADBEEF)
        code = self.lib.audit_page(limit, sector, ctypes.byref(target))
        return code, target.value

    def discard(self, limit: int, first_sector: int, sectors: int):
        return self.lib.audit_discard(limit, first_sector, sectors)

    def test_in_bounds_first_page(self):
        self.assertEqual(self.page(4, 0), (0, 0))

    def test_in_bounds_last_page(self):
        self.assertEqual(self.page(4, 24), (0, 3))

    def test_index_at_end_refused_without_setting_output(self):
        self.assertEqual(self.page(4, 32), (-errno.ERANGE, 0xDEADBEEF))

    def test_unaligned_read_or_write_sector_denied(self):
        for sector in (1, 7, 9, 31):
            with self.subTest(sector=sector):
                self.assertEqual(self.page(4, sector), (-errno.EINVAL, 0xDEADBEEF))

    def test_index_above_u32_does_not_alias_zero_or_one(self):
        for index in (1 << 32, (1 << 32) + 1, (1 << 32) + 3):
            with self.subTest(index=index):
                self.assertEqual(self.page(4, index * 8), (-errno.ERANGE, 0xDEADBEEF))

    def test_highest_valid_u32_page_index(self):
        self.assertEqual(self.page(U32_MAX, (U32_MAX - 1) * 8),
                         (0, U32_MAX - 1))

    def test_last_invalid_u32_page_index(self):
        self.assertEqual(self.page(U32_MAX, U32_MAX * 8),
                         (-errno.ERANGE, 0xDEADBEEF))

    def test_max_u64_sector_refused_before_narrowing(self):
        self.assertEqual(self.page(4, U64_MAX), (-errno.EINVAL, 0xDEADBEEF))
        self.assertEqual(self.page(4, U64_MAX - 7),
                         (-errno.ERANGE, 0xDEADBEEF))

    def test_single_page_discard(self):
        self.assertEqual(self.discard(4, 16, 8), 0)

    def test_full_extent_discard(self):
        self.assertEqual(self.discard(4, 0, 32), 0)

    def test_discard_ending_exactly_at_end(self):
        self.assertEqual(self.discard(4, 24, 8), 0)

    def test_discard_starting_at_end_refused(self):
        self.assertEqual(self.discard(4, 32, 8), -errno.ERANGE)

    def test_out_of_bounds_tail_is_denied_whole(self):
        for start, length in ((0, 40), (8, 32), (24, 16)):
            with self.subTest(start=start, length=length):
                self.assertEqual(self.discard(4, start, length), -errno.ERANGE)

    def test_discard_partial_page_refused(self):
        for start, length in ((0, 1), (0, 7), (8, 9), (7, 8)):
            with self.subTest(start=start, length=length):
                self.assertEqual(self.discard(4, start, length), -errno.EINVAL)

    def test_discard_high_sector_u32_alias_refused(self):
        self.assertEqual(self.discard(4, (1 << 32) * 8, 8), -errno.ERANGE)

    def test_discard_max_sector_no_overflow(self):
        self.assertEqual(self.discard(4, U64_MAX - 7, 16), -errno.ERANGE)
        self.assertEqual(self.discard(4, U64_MAX, 8), -errno.EINVAL)

    def test_zero_discard_preserves_previous_noop_for_aligned_sector(self):
        self.assertEqual(self.discard(4, 0, 0), 0)
        self.assertEqual(self.discard(4, 32, 0), 0)

    def test_zero_extent_has_no_invalid_side_effects(self):
        # The only side effect of the pure validation helper is its return.
        self.assertEqual(self.discard(0, 0, 0), 0)
        self.assertEqual(self.discard(0, 0, 8), -errno.ERANGE)

    def test_source_read_checks_index_before_observing_mapping(self):
        source = extract_function(self.source, "swapz_process_read")
        self.assertIn("swapz_checked_page_index", source)
        self.assertLess(source.index("swapz_checked_page_index"),
                        source.index("swapz_read_staged"))

    def test_source_write_checks_index_before_generation_and_copy(self):
        source = extract_function(self.source, "swapz_process_write")
        self.assertIn("swapz_checked_page_index", source)
        self.assertLess(source.index("swapz_checked_page_index"),
                        source.index("context->generations[logical_page]"))
        self.assertLess(source.index("swapz_checked_page_index"),
                        source.index("swapz_copy_from_bio"))

    def test_source_discard_validates_before_any_flush_or_invalidation(self):
        source = extract_function(self.source, "swapz_process_discard")
        check = source.index("swapz_checked_discard_range")
        self.assertLess(check, source.index("swapz_flush_pack"))
        self.assertLess(check, source.index("while (remaining)"))
        self.assertLess(check, source.index("swapz_invalidate_mapping"))
        self.assertLess(check, source.index("++context->generations[logical_page]"))

    def test_source_discard_does_not_pretruncate_high_sector(self):
        source = extract_function(self.source, "swapz_process_discard")
        self.assertIn("sector_t sector =", source)
        self.assertIn("sector_t remaining =", source)
        self.assertNotIn("logical_page = (u32)(sector / SWAPZ_BLOCK_SECTORS);\n"
                         "\t\tif (logical_page >= context->logical_pages)", source)

    def test_negative_mutation_widened_page_admission_is_detected(self):
        mutated = self.source.replace("if (index >= logical_pages)",
                                      "if (index > logical_pages)", 1)
        self.assertNotEqual(mutated, self.source)
        with tempfile.TemporaryDirectory(prefix="swapz-guard-mutant-") as root:
            mutant = compile_source(mutated, Path(root))
            out = ctypes.c_uint32(0xDEADBEEF)
            self.assertEqual(mutant.audit_page(4, 32, ctypes.byref(out)), 0)

    def test_negative_mutation_discard_tail_check_is_detected(self):
        mutated = self.source.replace("page_count > logical_pages - first_page",
                                      "page_count < logical_pages - first_page", 1)
        self.assertNotEqual(mutated, self.source)
        with tempfile.TemporaryDirectory(prefix="swapz-range-mutant-") as root:
            mutant = compile_source(mutated, Path(root))
            self.assertEqual(mutant.audit_discard(4, 24, 16), 0)

    def test_source_kernel_gc_does_not_reclaim_live_victim(self):
        source = extract_function(self.source, "swapz_clean_segment")
        pack = source.index("swapz_flush_pack")
        batch = source.index("swapz_flush_write_batch")
        verify = source.index("context->segment_live_blocks[victim] != 0")
        free = source.index("context->segment_state[victim] = SWAPZ_SEGMENT_FREE")
        self.assertLess(pack, batch)
        self.assertLess(batch, verify)
        self.assertLess(verify, free)

    def test_source_previous_generation_is_committed_before_increment(self):
        source = extract_function(self.source, "swapz_process_write")
        self.assertLess(source.index("swapz_commit_previous_generation"),
                        source.index("generation = previous_generation + 1"))
        self.assertIn("context->generations[logical_page] = previous_generation", source)

    def test_source_flush_orders_pack_batch_and_lower_flush(self):
        source = extract_function(self.source, "swapz_process_flush")
        self.assertLess(source.index("swapz_flush_pack"), source.index("swapz_flush_write_batch"))
        self.assertLess(source.index("swapz_flush_write_batch"),
                        source.index("blkdev_issue_flush"))

    def test_source_staged_publication_requires_current_generation(self):
        source = extract_function(self.source, "swapz_finalize_stream_buffer")
        self.assertIn("swapz_stream_record_current(context, record)", source)
        self.assertLess(source.index("swapz_stream_record_current(context, record)"),
                        source.index("swapz_install_mapping"))

    def test_source_4k_page_and_sector_geometry_remain_bound(self):
        self.assertIn("#if PAGE_SIZE != 4096", self.source)
        self.assertIn("#define SWAPZ_BLOCK_BYTES PAGE_SIZE", self.source)
        self.assertIn("#define SWAPZ_BLOCK_SECTORS (SWAPZ_BLOCK_BYTES >> SECTOR_SHIFT)",
                      self.source)

    def test_source_discard_range_check_must_handle_tail_before_mutation(self):
        source = extract_function(self.source, "swapz_checked_discard_range")
        self.assertIn("page_count > logical_pages - first_page", source)
        self.assertLess(source.index("first_page >= logical_pages"),
                        source.index("page_count > logical_pages - first_page"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
