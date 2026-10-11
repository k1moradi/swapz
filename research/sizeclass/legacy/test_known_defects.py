#!/usr/bin/env python3
"""Five intentionally RED rootless regression tests for the original reviewer snippets.

These are expected to fail UNTIL corrected implementations are contributed.
Do not mask these failures, run against privileged storage, or put them in green CI.
"""
import importlib.util
from pathlib import Path
import sys
import unittest

HERE = Path(__file__).resolve().parent


def load(name):
    spec = importlib.util.spec_from_file_location(name, HERE / (name + ".py"))
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


class LegacyReviewerRegression(unittest.TestCase):
    def test_reviewer1_64k_uses_full_31_record_capacity(self):
        m = load("reviewer1_allocator")
        a = m.SizeClassAllocator(superblock_size_kb=64)
        for slot in range(62):
            a.allocate_and_pack(slot, 1, 2072)
        counts = [len(s.records) for s in a.sealed_slabs + a.active_slabs]
        self.assertEqual(counts, [31, 31], "95%-fullness threshold seals at 30")

    def test_reviewer1_does_not_publish_disk_mapping_before_io_completion(self):
        m = load("reviewer1_allocator")
        a = m.SizeClassAllocator(superblock_size_kb=8)
        a.allocate_and_pack(5, 1, 2072)
        self.assertNotIn(
            5, a.mapping_table,
            "model publishes disk-authoritative mapping without lower-I/O completion",
        )

    def test_reviewer2_serialized_offsets_are_byte_accurate(self):
        m = load("reviewer2_allocator")
        a = m.SizeClassAllocator("8K", max_staged_slabs=1)
        for slot, letter in enumerate((b"A", b"B", b"C")):
            a.write_record(slot, 1, letter * 2072)
        physical = a.active_slabs[0].serialize()
        for slot, letter in enumerate((b"A", b"B", b"C")):
            off = a.mapping_table[slot]["offset"]
            self.assertEqual(physical[off:off+2072], letter * 2072)

    def test_reviewer2_gc_packs_three_records_per_eight_k_extent(self):
        m = load("reviewer2_gc")
        a = m.GCSimulator(extent_size=8192)
        for slot in range(3):
            self.assertTrue(a.write_page(slot, 2072))
        self.assertEqual(a.foreground_bytes_written, 8192)

    def test_reviewer2_gc_does_not_count_failed_logical_writes(self):
        m = load("reviewer2_gc")
        a = m.GCSimulator(extent_size=4096)
        self.assertFalse(a.write_page(5, 2072, fail_injection=True))
        self.assertEqual(a.logical_bytes_in, 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
