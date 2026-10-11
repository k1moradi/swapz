#!/usr/bin/env python3
"""Rootless block-native geometry invariants, not a device-I/O simulation."""
import unittest
import geometry as g


class Geometry(unittest.TestCase):
    def test_sequential_cannot_reopen_old_bins(self):
        pages = [2200] * 8 + [1600] * 8
        self.assertEqual(len(g.greedy(pages)), 12)
        self.assertEqual(len(g.bounded_best_fit(pages, 16)), 8)

    def test_alternating_pairs(self):
        self.assertEqual(len(g.greedy([v for _ in range(8) for v in (2200, 1600)])), 8)

    def test_uniform_2072_cannot_pair_in_four_k(self):
        pages = [2072] * 112
        self.assertEqual(len(g.greedy(pages)), 112)
        self.assertEqual(len(g.bounded_best_fit(pages, 16)), 112)

    def test_three_fit_eight_k_with_one_straddle(self):
        bins = g.size_class_slab([2072] * 3, 2)
        self.assertEqual(len(bins), 1)
        self.assertEqual(bins[0].bytes_written, 8192)
        self.assertEqual(bins[0].bytes_needed, 6248)
        self.assertEqual(bins[0].physical_read_blocks(), [1, 2, 1])

    def test_equal_flush_window(self):
        pages = [1048] * 16
        self.assertEqual(len(g.bounded_ordered(pages)), len(g.bounded_best_fit(pages)))

    def test_seven_fit_sixteen_k(self):
        bins = g.size_class_slab([2072] * 7, 4)
        self.assertEqual(bins[0].bytes_needed, 14568)
        self.assertEqual(bins[0].bytes_written, 16384)

    def test_thirty_one_fit_sixty_four_k(self):
        bins = g.size_class_slab([2072] * 31, 16)
        self.assertEqual(bins[0].bytes_needed, 64488)
        self.assertEqual(bins[0].bytes_written, 65536)

    def test_underfilled_slabs_cost_bytes(self):
        pages = [2072] * 16
        self.assertEqual(g.summary(g.bounded_size_class_slabs(pages, 16))["gross_logical_to_physical"], 1)
        self.assertAlmostEqual(g.summary(g.bounded_size_class_slabs(pages, 2))["gross_logical_to_physical"], 4/3)
        self.assertAlmostEqual(g.summary(g.bounded_size_class_slabs(pages, 4))["gross_logical_to_physical"], 4/3)

    def test_gc_victim_live_fraction_not_global_occupancy(self):
        self.assertAlmostEqual(g.gc_sensitivity(1.5)["victim_live_fraction_break_even"], 1/3)
        self.assertEqual(g.gc_sensitivity(1.5)["net_ratio_by_victim_live_fraction"]["0.5"], 0.75)

    def test_reject_bad_payloads(self):
        with self.assertRaises(ValueError):
            g.size_class_slab([0], 2)
        with self.assertRaises(ValueError):
            g.bounded_best_fit([-1], 16)

    def test_raw_fallback_is_four_k(self):
        bins = g.size_class_slab([4096, 2072, 2072, 2072], 2)
        self.assertEqual(sum(b.bytes_written for b in bins), 4096 + 8192)
        self.assertEqual(sum(b.bytes_needed for b in bins), 4096 + 6248)


if __name__ == "__main__":
    unittest.main(verbosity=2)
