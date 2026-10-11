"""Deterministic rootless acceptance tests for research allocator."""
import unittest

from allocator import (AllocatorError, Backpressure, BLOCK_BYTES, CorruptExtent,
                       Mapping, SizeClassAllocator, pack_windows)


def commit_all(allocator: SizeClassAllocator):
    return [item for extent_id in allocator.flush() for item in allocator.complete(extent_id, success=True)]


class AllocatorTests(unittest.TestCase):
    def test_full_31_record_capacity_and_exact_byte_readback(self):
        for count, capacity in ((1, 1), (2, 3), (4, 7), (16, 31)):
            with self.subTest(blocks=count):
                allocator = SizeClassAllocator(count, max_buffered_bytes=200000)
                records = {slot: bytes([slot]) * 2072 for slot in range(capacity)}
                for slot, payload in records.items():
                    allocator.stage(slot, 1, payload)
                self.assertEqual(len(allocator.staged), 1)
                submitted = allocator.flush()
                self.assertEqual(len(submitted), 1)
                self.assertFalse(allocator.committed)
                self.assertEqual(allocator.complete(submitted[0], success=True),
                                 [(slot, 1) for slot in records])
                for slot, expected in records.items():
                    self.assertEqual(allocator.read(slot).payload, expected)
                self.assertEqual(allocator.completed_physical_bytes, count * BLOCK_BYTES)
                self.assertEqual(allocator.completed_logical_bytes, capacity * BLOCK_BYTES)

    def test_staging_and_inflight_never_authoritative(self):
        allocator = SizeClassAllocator(2)
        allocator.stage(5, 1, b'A' * 2072)
        self.assertIsNone(allocator.read(5))
        submitted = allocator.flush()
        self.assertIsNone(allocator.read(5))
        self.assertEqual(allocator.completed_physical_bytes, 0)
        allocator.complete(submitted[0], success=True)
        self.assertEqual(allocator.read(5).payload, b'A' * 2072)

    def test_torn_write_preserves_prior_mapping_and_siblings(self):
        allocator = SizeClassAllocator(2)
        allocator.stage(1, 1, b'A' * 2072)
        allocator.stage(2, 1, b'B' * 2072)
        commit_all(allocator)
        allocator.stage(1, 2, b'C' * 2072)
        extent_id, = allocator.flush()
        self.assertEqual(allocator.complete(extent_id, success=False, partial_blocks=1), [])
        self.assertEqual(allocator.read(1).payload, b'A' * 2072)
        self.assertEqual(allocator.read(2).payload, b'B' * 2072)
        self.assertEqual(allocator.completed_logical_bytes, 2 * BLOCK_BYTES)
        self.assertEqual(allocator.partial_physical_bytes, BLOCK_BYTES)
        self.assertEqual(allocator.completed_physical_bytes, 2 * BLOCK_BYTES)
        self.assertEqual(allocator.failed_operations, 1)

    def test_superseded_inflight_does_not_replace_authority(self):
        allocator = SizeClassAllocator(1)
        allocator.stage(7, 1, b'A' * 2000)
        first, = allocator.flush()
        allocator.stage(7, 2, b'B' * 1900)
        second, = allocator.flush()
        self.assertEqual(allocator.complete(second, success=True), [(7, 2)])
        self.assertEqual(allocator.complete(first, success=True), [])
        self.assertEqual(allocator.read(7).payload, b'B' * 1900)
        self.assertEqual(allocator.completed_logical_bytes, BLOCK_BYTES)
        with self.assertRaises(AllocatorError):
            allocator.stage(7, 1, b'C' * 100)

    def test_supersede_staged_reclaims_packing_room(self):
        allocator = SizeClassAllocator(1)
        allocator.stage(1, 1, b'A' * 2000)
        allocator.stage(1, 2, b'B' * 2072)
        allocator.stage(2, 1, b'C' * 1000)
        commit_all(allocator)
        self.assertEqual(allocator.read(1).payload, b'B' * 2072)
        self.assertEqual(allocator.read(2).payload, b'C' * 1000)
        self.assertEqual(allocator.completed_logical_bytes, 2 * BLOCK_BYTES)

    def test_raw_fallback_never_pads_compressed_data(self):
        allocator = SizeClassAllocator(2)
        with self.assertRaises(AllocatorError):
            allocator.stage(1, 1, b'C' * 4050)
        allocator.stage(1, 1, b'C' * 4050, raw_page=b'R' * BLOCK_BYTES)
        commit_all(allocator)
        self.assertEqual(allocator.read(1).payload, b'R' * BLOCK_BYTES)
        self.assertEqual(allocator.completed_physical_bytes, BLOCK_BYTES)

    def test_one_and_two_record_partial_flushing(self):
        for count in (1, 2):
            with self.subTest(count=count):
                allocator = SizeClassAllocator(16)
                for slot in range(count):
                    allocator.stage(slot, 1, b'A' * 2072)
                commit_all(allocator)
                self.assertEqual(allocator.completed_physical_bytes, 16 * BLOCK_BYTES)
                self.assertEqual(allocator.completed_logical_bytes, count * BLOCK_BYTES)

    def test_spanning_reads_count_actual_subblocks(self):
        allocator = SizeClassAllocator(2)
        for slot in range(3):
            allocator.stage(slot, 1, bytes([slot]) * 2072)
        commit_all(allocator)
        self.assertEqual([allocator.read(slot).payload_blocks for slot in range(3)], [1, 2, 1])
        self.assertEqual([allocator.read(slot, metadata_cached=False).total_read_blocks
                          for slot in range(3)], [1, 2, 2])

    def test_corrupt_payload_and_mapping_fail_closed(self):
        allocator = SizeClassAllocator(2)
        allocator.stage(5, 1, b'Q' * 2072)
        commit_all(allocator)
        mapping = allocator.committed[5]
        image = bytearray(allocator.media[mapping.extent_id])
        image[mapping.offset] ^= 1
        allocator.media[mapping.extent_id] = bytes(image)
        with self.assertRaises(CorruptExtent):
            allocator.read(5)
        image[mapping.offset] ^= 1
        allocator.media[mapping.extent_id] = bytes(image)
        allocator.committed[5] = Mapping(mapping.extent_id, 1, mapping.offset + 1,
                                         mapping.length, mapping.checksum, False)
        with self.assertRaises(CorruptExtent):
            allocator.read(5)

    def test_fail_closed_when_staging_budget_exceeded(self):
        allocator = SizeClassAllocator(16, max_buffered_bytes=4096,
                                       max_buffered_records=1, max_staged_extents=1,
                                       max_inflight_extents=1)
        allocator.stage(1, 1, b'A' * 2072)
        with self.assertRaises(Backpressure):
            allocator.stage(2, 1, b'B' * 2072)
        first, = allocator.flush()
        with self.assertRaises(Backpressure):
            allocator.stage(2, 1, b'B' * 2072)
        allocator.complete(first, success=True)
        allocator.stage(2, 1, b'B' * 2072)
        commit_all(allocator)

    def test_deadline_forces_partial_flush_without_phantom_commit(self):
        allocator = SizeClassAllocator(16, flush_deadline=3)
        allocator.stage(1, 1, b'A' * 2072)
        self.assertEqual(allocator.tick(2), [])
        submitted = allocator.tick(1)
        self.assertEqual(len(submitted), 1)
        self.assertIsNone(allocator.read(1))
        allocator.complete(submitted[0], success=True)
        self.assertEqual(allocator.read(1).payload, b'A' * 2072)

    def test_source_order_and_windowed_reorder_identical_cutpoints(self):
        values = [2200] * 8 + [1600] * 8
        # The 32+32 wire overhead per record still permits 2200+1600 in 4K.
        self.assertEqual(len(pack_windows(values, [16], strategy='ordered')), 12)
        self.assertEqual(len(pack_windows(values, [16], strategy='best_fit')), 8)
        self.assertEqual(len(pack_windows(values, [8, 8], strategy='best_fit')), 12)
        self.assertEqual(len(pack_windows(values, [8, 8], strategy='ordered')), 12)

    def test_repeated_staged_overwrite_keeps_real_memory_bounded(self):
        allocator = SizeClassAllocator(1, max_buffered_bytes=4096, max_buffered_records=1)
        for generation in range(1, 1001):
            allocator.stage(9, generation, b'X' * 2072)
        self.assertEqual(sum(len(extent.records) for extent in allocator.staged), 1)
        commit_all(allocator)
        self.assertEqual(allocator.read(9).generation, 1000)
        self.assertEqual(allocator.completed_logical_bytes, BLOCK_BYTES)

    def test_failure_requires_new_generation_for_retry(self):
        allocator = SizeClassAllocator(1)
        allocator.stage(2, 1, b'A' * 2072)
        failed_extent, = allocator.flush()
        self.assertEqual(allocator.complete(failed_extent, success=False), [])
        with self.assertRaises(AllocatorError):
            allocator.stage(2, 1, b'A' * 2072)
        allocator.stage(2, 2, b'A' * 2072)
        commit_all(allocator)
        self.assertEqual(allocator.read(2).generation, 2)
        self.assertEqual(allocator.completed_logical_bytes, BLOCK_BYTES)
        self.assertEqual(allocator.submitted_physical_bytes, 2 * BLOCK_BYTES)

    def test_corrupt_sibling_data_does_not_hide_good_payload(self):
        allocator = SizeClassAllocator(2)
        for slot in range(3):
            allocator.stage(slot, 1, bytes([slot]) * 2072)
        commit_all(allocator)
        bad_mapping = allocator.committed[2]
        image = bytearray(allocator.media[bad_mapping.extent_id])
        image[bad_mapping.offset] ^= 1
        allocator.media[bad_mapping.extent_id] = bytes(image)
        self.assertEqual(allocator.read(0).payload, b'\x00' * 2072)
        with self.assertRaises(CorruptExtent):
            allocator.read(2)

    def test_reject_invalid_extent_completions(self):
        allocator = SizeClassAllocator(2)
        allocator.stage(1, 1, b'A' * 2072)
        extent_id, = allocator.flush()
        with self.assertRaises(ValueError):
            allocator.complete(extent_id, success=True, partial_blocks=1)
        allocator.complete(extent_id, success=True)
        with self.assertRaises(AllocatorError):
            allocator.complete(extent_id, success=True)


if __name__ == '__main__':
    unittest.main(verbosity=2)
