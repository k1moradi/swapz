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
