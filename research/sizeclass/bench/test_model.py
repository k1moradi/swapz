"""Adversarial rootless tests for aligned zspage-inspired media simulation."""
from dataclasses import replace
import random
import unittest

from model import (BLOCK_BYTES, DESCRIPTOR, HEADER, MAX_RECORDS, MediaError,
                   Record, Replay, choose_pack, serialize)
from run import synthetic_trace, run_trace, audit_lengths_trace


def byte_count(packed):
    return sum(blocks * BLOCK_BYTES for blocks, _ in packed)


class GeometryTests(unittest.TestCase):
    def test_fifty_percent_uniform_requires_spanning(self):
        records = [Record(index, 1, b'A' * 2072) for index in range(16)]
        self.assertEqual(byte_count(choose_pack(records, 'ordered4')), 65536)
        self.assertEqual(byte_count(choose_pack(records, 'bestfit4')), 65536)
        self.assertEqual(byte_count(choose_pack(records, 'fixed8')), 49152)
        self.assertEqual(byte_count(choose_pack(records, 'fixed16')), 49152)
        self.assertEqual(byte_count(choose_pack(records, 'fixed64')), 65536)
        self.assertEqual(byte_count(choose_pack(records, 'adaptive')), 49152)

    def test_adaptive_favors_16k_at_32_record_flush(self):
        records = [Record(index, 1, b'A' * 2072) for index in range(32)]
        self.assertEqual(byte_count(choose_pack(records, 'adaptive')), 81920)

    def test_adaptive_avoids_partial_extents(self):
        records = [Record(index, 1, b'A' * 2072) for index in range(2)]
        self.assertEqual([blocks for blocks, _ in choose_pack(records, 'adaptive')], [1, 1])

    def test_75_percent_is_packed_as_three_records_per_4k(self):
        records = [Record(index, 1, b'A' * 1048) for index in range(16)]
        self.assertEqual(byte_count(choose_pack(records, 'adaptive')), 6 * BLOCK_BYTES)

    def test_clustered_bestfit_only_within_bounded_window(self):
        records = [Record(i, 1, b'A' * (2200 if i < 8 else 1600)) for i in range(16)]
        self.assertEqual(byte_count(choose_pack(records, 'ordered4')), 12 * BLOCK_BYTES)
        self.assertEqual(byte_count(choose_pack(records, 'bestfit4')), 8 * BLOCK_BYTES)
        separate_windows = choose_pack(records[:8], 'bestfit4') + choose_pack(records[8:], 'bestfit4')
        self.assertEqual(byte_count(separate_windows), 12 * BLOCK_BYTES)

    def test_64k_fits_31_but_not_32_records(self):
        records = [Record(index, 1, b'A' * 2072) for index in range(32)]
        packed = choose_pack(records[:31], 'fixed64')
        self.assertEqual([len(items) for _, items in packed], [31])
        self.assertEqual(sorted(len(items) for _, items in choose_pack(records, 'fixed64')), [1, 31])

    def test_descriptor_limit_is_hard_even_for_tiny_payloads(self):
        records = [Record(index, 1, b'A') for index in range(129)]
        packed = choose_pack(records, 'fixed64')
        self.assertEqual(sorted(len(items) for _, items in packed), [1, 64, 64])

    def test_roundtrip_all_extent_classes(self):
        for blocks, count in ((1, 1), (2, 3), (4, 7), (16, 31)):
            with self.subTest(blocks=blocks):
                records = [Record(index, 1, bytes([index]) * 2072) for index in range(count)]
                image, offsets = serialize(records, blocks)
                self.assertEqual(len(image), blocks * BLOCK_BYTES)
                self.assertEqual(offsets[0], HEADER.size + count * DESCRIPTOR.size)
                for record, offset in zip(records, offsets):
                    self.assertEqual(image[offset:offset + len(record.payload)], record.payload)

    def test_raw_needs_original_page(self):
        with self.assertRaises(ValueError):
            Record(1, 1, b'A' * 3800, raw=True)
        raw = Record(1, 1, b'A' * BLOCK_BYTES, raw=True)
        image, offsets = serialize([raw], 1)
        self.assertEqual(image, raw.payload)
        self.assertEqual(offsets, (0,))

    def test_read_penalty_does_not_hurt_4k_layout(self):
        records = [Record(index, 1, b'A' * 1048) for index in range(12)]
        self.assertEqual(byte_count(choose_pack(records, 'adaptive', read_penalty_bytes=4096)),
                         4 * BLOCK_BYTES)

    def test_reject_invalid_record_identity_and_sizes(self):
        with self.assertRaises(ValueError):
            Record(-1, 1, b'A')
        with self.assertRaises(ValueError):
            Record(1, 1, b'')
        with self.assertRaises(ValueError):
            Record(1, 1, b'A' * 3569)
        with self.assertRaises(ValueError):
            choose_pack([], 'unknown')


class OwnershipAndGCTests(unittest.TestCase):
    def test_no_publication_before_flush(self):
        replay = Replay('fixed8', window=16)
        replay.stage(1, b'A' * 2072)
        self.assertIsNone(replay.read(1))
        replay.flush()
        self.assertEqual(replay.read(1), b'A' * 2072)

    def test_preserves_sibling_on_overwrite(self):
        replay = Replay('fixed8', window=3)
        for slot in range(3):
            replay.stage(slot, bytes([slot]) * 2072)
        replay.stage(0, b'Z' * 2072)
        replay.flush()
        self.assertEqual(replay.read(0), b'Z' * 2072)
        self.assertEqual(replay.read(1), b'\x01' * 2072)
        self.assertEqual(replay.read(2), b'\x02' * 2072)

    def test_generation_increments_only_across_windows(self):
        replay = Replay('adaptive', window=2)
        replay.stage(1, b'A' * 1048)
        with self.assertRaises(ValueError):
            replay.stage(1, b'B' * 1048)
        replay.flush()
        replay.stage(1, b'B' * 1048)
        replay.flush()
        self.assertEqual(replay.mappings[1].generation, 2)
        self.assertEqual(replay.read(1), b'B' * 1048)

    def test_serialized_payload_corruption_fails_closed(self):
        replay = Replay('fixed8', window=1)
        replay.stage(1, b'A' * 2072)
        mapping = replay.mappings[1]
        extent = replay.media[mapping.extent_id]
        image = bytearray(extent.image)
        image[mapping.offset] ^= 0x80
        replay.media[extent.identifier] = replace(extent, image=bytes(image))
        with self.assertRaises(MediaError):
            replay.read(1)

    def test_tampered_mapping_and_descriptor_fail_closed(self):
        replay = Replay('fixed8', window=1)
        replay.stage(1, b'A' * 2072)
        mapping = replay.mappings[1]
        replay.mappings[1] = replace(mapping, offset=mapping.offset + 1)
        with self.assertRaises(MediaError):
            replay.read(1)
        replay.mappings[1] = mapping
        extent = replay.media[mapping.extent_id]
        image = bytearray(extent.image)
        image[HEADER.size + 4] = 0xff
        replay.media[extent.identifier] = replace(extent, image=bytes(image))
        with self.assertRaises(MediaError):
            replay.read(1)

    def test_three_record_8k_spanning_read_count(self):
        replay = Replay('fixed8', window=3)
        for slot in range(3):
            replay.stage(slot, b'A' * 2072)
        self.assertEqual([replay._read_mapping(replay.mappings[slot])[1] for slot in range(3)],
                         [1, 2, 2])  # last payload needs metadata block 0 as well

    def _fixture_with_closed_segment_and_dead_records(self):
        replay = Replay('ordered4', segment_count=5, reserve_segments=1, window=16)
        for index in range(288):
            replay.stage(index, b'A' * 2072)
        replay.flush()
        # Force invalidation of most of the first 256-record segment.
        for index in range(200):
            replay.stage(index, b'B' * 2072)
        replay.flush()
        self.assertEqual(replay.segments[0].state, 'closed')
        return replay

    def test_gc_relocates_real_survivors_and_reclaims_victim(self):
        replay = self._fixture_with_closed_segment_and_dead_records()
        old = {slot: replay.read(slot) for slot in range(288)}
        old_completed = replay.completed_logical_bytes
        self.assertTrue(replay.collect_one())
        self.assertEqual(replay.completed_logical_bytes, old_completed)
        self.assertGreater(replay.gc_write_bytes, 0)
        self.assertGreater(replay.gc_read_blocks, 0)
        self.assertEqual(replay.segments[0].state, 'free')
        for slot, payload in old.items():
            self.assertEqual(replay.read(slot), payload)

    def test_interrupted_gc_preserves_old_live_mappings(self):
        replay = self._fixture_with_closed_segment_and_dead_records()
        originals = dict(replay.mappings)
        self.assertFalse(replay.collect_one(fail_after_extents=1))
        self.assertEqual(replay.mappings, originals)
        self.assertEqual(replay.segments[0].state, 'closed')
        self.assertGreater(replay.gc_write_bytes, 0)
        self.assertEqual(replay.failed_gc_runs, 1)

    def test_failed_extent_preserves_committed_mapping(self):
        replay = Replay('fixed8', window=1)
        replay.stage(1, b'A' * 2072)
        before = replay.mappings[1]
        failed = Record(1, 2, b'B' * 2072)
        self.assertIsNone(replay._write_extent([failed], 2, gc=False, fail=True, partial_blocks=1))
        self.assertEqual(replay.mappings[1], before)
        self.assertEqual(replay.read(1), b'A' * 2072)
        self.assertEqual(replay.foreground_write_bytes, 8192 + 4096)
        self.assertEqual(replay.foreground_submitted_bytes, 2 * 8192)

    def test_seeded_comparison_replays_same_trace(self):
        trace = synthetic_trace('mixed', operations=256, window=16, working_set=64, seed=42)
        results = [run_trace(trace, policy=policy, window=16, segments=6,
                             reserve_segments=1, read_penalty_bytes=0,
                             read_seed=55, reads=30)
                   for policy in ('ordered4', 'bestfit4', 'fixed8', 'fixed16', 'adaptive')]
        self.assertEqual({result['completed_logical_bytes'] for result in results}, {256 * 4096})
        self.assertEqual({result['upper_reads'] if 'upper_reads' in result else result['upper_read_operations'] for result in results}, {30})
        self.assertGreater(results[-1]['net_reduction'], results[0]['net_reduction'])

    def test_foreground_bounded_space_fails_not_false_success(self):
        replay = Replay('ordered4', segment_count=3, reserve_segments=1, window=16)
        for index in range(600):
            replay.stage(index, b'A' * 2072)
        replay.flush()
        result = replay.report()
        self.assertGreater(result['failed_logical_writes'], 0)
        self.assertLess(result['completed_logical_bytes'], 600 * BLOCK_BYTES)
        self.assertEqual(result['foreground_physical_bytes'], result['completed_logical_bytes'])


if __name__ == '__main__':
    unittest.main(verbosity=2)
