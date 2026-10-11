#!/usr/bin/env python3
"""Rootless adversarial geometry checks for the experimental kernel bestfit4.

This is a reference model, NOT an executable replacement for kernel BIO,
mapping, generation, or asynchronous completion tests.
"""
import random
import unittest
from pathlib import Path

BLOCK = 4096
HEADER = 8
DESCRIPTOR = 8
MAX_RECORDS = 64
LOOKAHEAD_CAP = 128


def fits(group, record):
    return (not record['raw'] and len(group) < MAX_RECORDS and
            HEADER + (len(group) + 1) * DESCRIPTOR +
            sum(len(item['payload']) for item in group) +
            len(record['payload']) <= BLOCK)


def source_ordered(records):
    bins, group = [], []
    for record in records:
        if record['raw']:
            if group:
                bins.append(group)
                group = []
            bins.append([record])
        elif not fits(group, record):
            if group:
                bins.append(group)
            group = [record]
        else:
            group.append(record)
    if group:
        bins.append(group)
    return bins


def bounded_bestfit(records, source_blocks):
    """Match kernel planning: first unclaimed then largest fitting later record."""
    if len(records) > LOOKAHEAD_CAP:
        return None
    picked, groups = set(), []
    while len(picked) < len(records):
        first = next(index for index in range(len(records)) if index not in picked)
        group = [records[first]]
        picked.add(first)
        if not records[first]['raw']:
            while True:
                options = [index for index, record in enumerate(records)
                           if index not in picked and fits(group, record)]
                if not options:
                    break
                selected = max(options, key=lambda index: len(records[index]['payload']))
                picked.add(selected)
                group.append(records[selected])
        groups.append(group)
    if len(groups) >= source_blocks:
        return None
    return groups


def make_records(sizes, *, raw_slots=(), invalid_slots=()):
    return [{'slot': index,
             'raw': index in raw_slots,
             'live': index not in invalid_slots,
             'payload': bytes([index % 251]) * size}
            for index, size in enumerate(sizes)]


class KernelBestfitGeometry(unittest.TestCase):
    def check_same_survivors(self, records):
        original = source_ordered(records)
        survivors = [record for record in records if record['live']]
        packed = bounded_bestfit(survivors, len(original))
        effective = packed if packed is not None else source_ordered(survivors)
        self.assertLessEqual(len(effective), len(original))
        self.assertEqual(
            sorted(record['slot'] for group in effective for record in group),
            sorted(record['slot'] for record in survivors))
        for group in effective:
            if group[0]['raw']:
                self.assertEqual(len(group), 1)
                self.assertEqual(len(group[0]['payload']), BLOCK)
            else:
                self.assertLessEqual(HEADER + DESCRIPTOR * len(group) +
                                     sum(len(item['payload']) for item in group), BLOCK)
                self.assertLessEqual(len(group), MAX_RECORDS)
        return len(original), len(effective)

    def test_uniform_fifty_has_no_4k_reduction(self):
        records = make_records([2072] * 16)
        self.assertEqual(self.check_same_survivors(records), (16, 16))

    def test_clustered_mixed_reduces_twelve_to_eight(self):
        records = make_records([2200] * 8 + [1600] * 8)
        self.assertEqual(self.check_same_survivors(records), (12, 8))

    def test_identical_flush_points_do_not_assume_future_records(self):
        records = make_records([2200] * 8 + [1600] * 8)
        self.assertEqual(self.check_same_survivors(records[:8]), (8, 8))
        self.assertEqual(self.check_same_survivors(records[8:]), (4, 4))

    def test_raw_isolation_and_stale_cancellation(self):
        records = make_records([2000, 2000, BLOCK, 1600, 1600, 2072],
                               raw_slots=(2,), invalid_slots=(1, 4))
        original, effective = self.check_same_survivors(records)
        self.assertGreaterEqual(original, effective)

    def test_no_churn_for_already_optimal_order(self):
        records = make_records([2200, 1600] * 8)
        self.assertEqual(self.check_same_survivors(records), (8, 8))

    def test_tiny_records_still_respect_descriptor_cap(self):
        records = make_records([1] * 128)
        original, effective = self.check_same_survivors(records)
        self.assertLessEqual(effective, original)

    def test_excess_records_require_bounded_fallback(self):
        records = make_records([1] * 129)
        self.assertIsNone(bounded_bestfit(records, 3))

    def test_deterministic_randomized_mixed_layouts(self):
        generator = random.Random(0x5A21)
        for _ in range(2000):
            count = generator.randrange(1, 129)
            sizes = [generator.choice((32, 256, 1048, 1600, 2000, 2072,
                                       2200, 3000, 3500, BLOCK))
                     for _ in range(count)]
            raw_slots = tuple(index for index, length in enumerate(sizes)
                              if length == BLOCK)
            invalid_slots = tuple(index for index in range(count)
                                  if generator.randrange(6) == 0)
            records = make_records(sizes, raw_slots=raw_slots,
                                   invalid_slots=invalid_slots)
            self.check_same_survivors(records)

    def test_kernel_integration_is_explicit_opt_in_and_bounded(self):
        kernel = Path(__file__).resolve().parents[2] / 'kernel' / 'dm-swapz.c'
        content = kernel.read_text(encoding='utf-8')
        for required in (
                'SWAPZ_BESTFIT4_MAX_BATCH_BLOCKS 16U',
                'SWAPZ_BESTFIT4_MAX_RECORDS 128U',
                'swapz_compact_fill_buffer_bestfit4',
                'swapz_validate_compact_fill_buffer(context, buffer)',
                'swapz_stream_bios_match(context, buffer)',
                'planned_blocks >= old_count',
                'context->bestfit4_enabled',
                'vfree(context->bestfit4_source_data)',
                'kvfree(context->bestfit4_source_blocks)',
                'kvfree(context->bestfit4_records)'):
            self.assertIn(required, content)


if __name__ == '__main__':
    unittest.main(verbosity=2)
