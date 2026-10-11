"""Deterministic, rootless Issue #33 allocator tests (no lower I/O)."""
import dataclasses
import unittest

from allocator import BLOCK_BYTES, CorruptExtentError, ExtentAllocator


def finished(allocator):
    allocator.flush()
    for extent in list(allocator.in_flight.values()):
        allocator.complete(extent.identifier)


class AllocatorTests(unittest.TestCase):
    def test_capacity_and_exact_offsets(self):
        for blocks, count in ((1, 1), (2, 3), (4, 7), (16, 31)):
            with self.subTest(blocks=blocks):
                allocator = ExtentAllocator(block_count=blocks, max_staged_records=64)
                expected = {}
                for slot in range(count):
                    payload = bytes([slot]) * 2072
                    expected[slot] = payload
                    allocator.write(slot, payload)
                extents = allocator.flush()
                self.assertEqual(len(extents), 1)
                self.assertEqual(extents[0].physical_bytes, blocks * BLOCK_BYTES)
                self.assertEqual(allocator.mapping_table, {})
                allocator.complete(extents[0].identifier)
                for slot, payload in expected.items():
                    self.assertEqual(allocator.read(slot)[0], payload)
                    mapping = allocator.mapping_table[slot]
                    self.assertEqual(extents[0].content[mapping.offset:mapping.offset + mapping.length], payload)

    def test_max_sixty_four_descriptors_per_extent(self):
        allocator = ExtentAllocator(block_count=16, max_staged_records=130)
        for slot in range(130):
            allocator.write(slot, b'x')
        allocator.flush()
        self.assertEqual([len(e.records) for e in allocator.in_flight.values()], [64, 64, 2])

    def test_64k_32nd_record_requires_second_extent(self):
        allocator = ExtentAllocator(block_count=16, max_staged_records=64)
        for slot in range(32):
            allocator.write(slot, bytes([slot]) * 2072)
        self.assertEqual([len(e.records) for e in allocator.flush()], [31, 1])

    def test_4k_same_window_sequential_and_best_fit(self):
        lengths = [2200] * 8 + [1600] * 8
        counts = []
        for policy in ('sequential', 'best_fit'):
            allocator = ExtentAllocator(packing=policy)
            for slot, length in enumerate(lengths):
                allocator.write(slot, bytes([slot]) * length)
            counts.append(len(allocator.in_flight))
            finished(allocator)
            for slot, length in enumerate(lengths):
                self.assertEqual(allocator.read(slot)[0], bytes([slot]) * length)
        self.assertEqual(counts, [12, 8])

    def test_causal_flush_prevents_future_pairing(self):
        allocator = ExtentAllocator(packing='best_fit', max_staged_records=8)
        for slot in range(8):
            allocator.write(slot, b'A' * 2200)
        self.assertEqual(len(allocator.in_flight), 8)
        for slot in range(8, 16):
            allocator.write(slot, b'B' * 1600)
        self.assertEqual(len(allocator.in_flight), 12)

    def test_staging_and_inflight_are_not_disk_authority(self):
        allocator = ExtentAllocator(block_count=2)
        ticket = allocator.write(5, b'A' * 2072)
        self.assertEqual(ticket.state, 'staged')
        with self.assertRaises(KeyError):
            allocator.read(5)
        extent = allocator.flush()[0]
        self.assertEqual(ticket.state, 'in_flight')
        self.assertFalse(ticket.upper_completed)
        self.assertEqual(allocator.mapping_table, {})
        allocator.complete(extent.identifier)
        self.assertTrue(ticket.upper_completed)
        self.assertEqual(ticket.state, 'committed')
        self.assertEqual(allocator.read(5)[0], b'A' * 2072)

    def test_torn_write_preserves_old_mapping_and_siblings(self):
        allocator = ExtentAllocator(block_count=2)
        for slot in (5, 6, 7):
            allocator.write(slot, bytes([slot]) * 2072)
        finished(allocator)
        ticket = allocator.write(5, b'Z' * 2072)
        extent = allocator.flush()[0]
        allocator.complete(extent.identifier, success=False, completed_bytes=4096)
        self.assertFalse(ticket.upper_completed)
        self.assertEqual(ticket.state, 'failed')
        self.assertEqual(allocator.read(5)[0], bytes([5]) * 2072)
        self.assertEqual(allocator.read(6)[0], bytes([6]) * 2072)
        self.assertEqual(allocator.read(7)[0], bytes([7]) * 2072)
        self.assertEqual(allocator.completed_logical_bytes, 3 * 4096)
        self.assertEqual(allocator.completed_physical_bytes, 8192 + 4096)
        self.assertEqual(allocator.successful_physical_bytes, 8192)

    def test_stale_completion_does_not_overwrite_newer_generation(self):
        allocator = ExtentAllocator()
        old = allocator.write(12, b'A' * 1000)
        first_extent = allocator.flush()[0]
        new = allocator.write(12, b'B' * 1000)
        next_extent = allocator.flush()[0]
        allocator.complete(next_extent.identifier)
        allocator.complete(first_extent.identifier)
        self.assertEqual(old.state, 'superseded')
        self.assertTrue(old.upper_completed)
        self.assertEqual(new.state, 'committed')
        self.assertEqual(allocator.read(12)[0], b'B' * 1000)

    def test_failed_newer_generation_preserves_prior_success(self):
        allocator = ExtentAllocator()
        old = allocator.write(12, b'A' * 1000)
        first = allocator.flush()[0]
        new = allocator.write(12, b'B' * 1000)
        second = allocator.flush()[0]
        allocator.complete(second.identifier, success=False)
        allocator.complete(first.identifier)
        self.assertEqual(old.state, 'committed')
        self.assertEqual(new.state, 'failed')
        self.assertEqual(allocator.read(12)[0], b'A' * 1000)

    def test_overwrite_in_same_extent_keeps_latest_generation(self):
        allocator = ExtentAllocator(block_count=2)
        allocator.write(1, b'A' * 1000)
        allocator.write(1, b'B' * 1000)
        finished(allocator)
        self.assertEqual(allocator.read(1)[0], b'B' * 1000)

    def test_raw_fallback_and_raw_read(self):
        allocator = ExtentAllocator(block_count=16)
        raw = bytes(range(256)) * 16
        allocator.write(1, b'x' * 3800, raw_page=raw)
        finished(allocator)
        self.assertEqual(allocator.read(1), (raw, 1))
        self.assertEqual(allocator.successful_physical_bytes, BLOCK_BYTES)
        with self.assertRaises(ValueError):
            allocator.write(2, b'x' * 3800)

    def test_multiblock_read_amplification(self):
        allocator = ExtentAllocator(block_count=2)
        for slot in range(3):
            allocator.write(slot, b'x' * 2072)
        finished(allocator)
        self.assertEqual([allocator.read(slot)[1] for slot in range(3)], [1, 2, 1])

    def test_forced_short_flush_has_full_extent_cost(self):
        for count in (1, 2):
            allocator = ExtentAllocator(block_count=4)
            for slot in range(count):
                allocator.write(slot, b'a' * 2072)
            finished(allocator)
            self.assertEqual(allocator.successful_physical_bytes, 16384)
            self.assertEqual(allocator.completed_logical_bytes, 4096 * count)

    def test_deadline_forces_flush_before_new_write(self):
        allocator = ExtentAllocator(block_count=2, flush_deadline_ticks=3)
        allocator.write(0, b'a' * 2072, tick=1)
        allocator.write(1, b'b' * 2072, tick=3)
        allocator.write(2, b'c' * 2072, tick=4)
        self.assertEqual(len(allocator.in_flight), 1)
        self.assertEqual(len(allocator.staged), 1)
        with self.assertRaises(ValueError):
            allocator.advance_tick(2)

    def test_finite_space_and_inflight_backpressure(self):
        allocator = ExtentAllocator(max_physical_bytes=4096, max_in_flight_extents=1)
        allocator.write(0, b'x' * 100)
        allocator.flush()
        allocator.write(1, b'y' * 100)
        with self.assertRaises(BufferError):
            allocator.flush()
        self.assertEqual(len(allocator.staged), 1)
        self.assertNotIn(1, allocator.mapping_table)
        self.assertEqual(allocator.allocated_physical_bytes, 4096)

    def test_invalid_completion_does_not_lose_pending_extent(self):
        allocator = ExtentAllocator(block_count=2)
        allocator.write(1, b'x' * 2072)
        extent = allocator.flush()[0]
        with self.assertRaises(ValueError):
            allocator.complete(extent.identifier, success=True, completed_bytes=4096)
        with self.assertRaises(ValueError):
            allocator.complete(extent.identifier, success=False, completed_bytes=1)
        self.assertIn(extent.identifier, allocator.in_flight)

    def test_corrupted_extent_fails_closed(self):
        allocator = ExtentAllocator(block_count=2)
        allocator.write(1, b'a' * 2072)
        finished(allocator)
        location = allocator.mapping_table[1]
        allocator.mapping_table[1] = dataclasses.replace(location, offset=1)
        with self.assertRaises(CorruptExtentError):
            allocator.read(1)
        allocator.mapping_table[1] = location
        allocator.committed_extents[location.extent_identifier] = b'X' * 8192
        with self.assertRaises(CorruptExtentError):
            allocator.read(1)

    def test_invalid_payload_and_device_geometry(self):
        with self.assertRaises(ValueError):
            ExtentAllocator(block_count=3)
        with self.assertRaises(ValueError):
            ExtentAllocator(max_physical_bytes=4097)
        with self.assertRaises(ValueError):
            ExtentAllocator(max_staged_records=1.5)
        allocator = ExtentAllocator()
        with self.assertRaises(ValueError):
            allocator.write(-1, b'a')
        with self.assertRaises(ValueError):
            allocator.write(0, b'')
        with self.assertRaises(ValueError):
            allocator.write(0, b'a' * 4097)


if __name__ == '__main__':
    unittest.main(verbosity=2)
