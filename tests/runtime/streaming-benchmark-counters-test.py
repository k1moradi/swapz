#!/usr/bin/env python3
"""Rootless regression tests for real-format swapz status accounting."""
import importlib.util
from pathlib import Path
import unittest

MODULE_PATH = Path(__file__).resolve().parent / "streaming-benchmark-counters.py"
spec = importlib.util.spec_from_file_location("swapz_benchmark_counters", MODULE_PATH)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


BASE = (
    "0 65536 swapz strategy=opportunistic batch_kib=64 segment=0/8 "
    "lower_discard=off failed=0 logical_write=40960 physical_write=40960 "
    "compressed_payload=20000 compressed_pages=10 raw_pages=0 gc_write=0 "
    "gc_victims=0 physical_write_reqs=1"
)


def status(**kw):
    s = BASE
    for name, value in kw.items():
        import re
        s = re.sub(r"\b" + re.escape(name) + r"=[^ ]+", name + "=" + str(value), s)
    return s


class Counters(unittest.TestCase):
    def compute(self, pre=BASE, post=None, lower_pre="0 0 0 80", lower_post="0 0 0 160", expected=40960):
        post = post if post is not None else status(
            logical_write=81920, physical_write=81920, compressed_pages=20,
            compressed_payload=40000, physical_write_reqs=2,
        )
        return mod.compute(pre, post, lower_pre, lower_post, 10_500_000_000, expected)

    def test_real_format_and_units(self):
        result = self.compute()
        self.assertEqual(result["effective_io_reduction"], 1)
        self.assertEqual(result["logical_write_bytes"], 40960)
        self.assertEqual(result["lower_sysfs_write_bytes"], 40960)
        self.assertEqual(result["raw_fallback_fraction_of_compression_operations"], 0)

    def test_compressed_three_to_one_and_gc(self):
        # 12 logical pages, four 4K containers including one GC container.
        post = status(logical_write=90112, physical_write=57344,
                      compressed_pages=22, compressed_payload=32000,
                      gc_write=4096, gc_victims=1, physical_write_reqs=2)
        result = self.compute(post=post, lower_post="0 0 0 112", expected=49152)
        self.assertEqual(result["effective_io_reduction"], 3)
        self.assertEqual(result["gc_write_bytes"], 4096)

    def test_reject_duplicate(self):
        with self.assertRaisesRegex(ValueError, "duplicate"):
            mod.parse_status(BASE + " logical_write=5")

    def test_reject_missing_or_nonnumeric(self):
        with self.assertRaisesRegex(ValueError, "missing/nondecimal"):
            mod.parse_status(BASE.replace("logical_write=40960", "logical_write=no"))
        with self.assertRaisesRegex(ValueError, "missing/nondecimal"):
            mod.parse_status(BASE.replace(" raw_pages=0", ""))

    def test_reject_bad_target(self):
        with self.assertRaisesRegex(ValueError, "expected"):
            mod.parse_status(BASE.replace(" swapz ", " linear "))

    def test_reject_failed_target(self):
        with self.assertRaisesRegex(ValueError, "failed"):
            mod.parse_status(status(failed=1))

    def test_reject_changed_strategy(self):
        with self.assertRaisesRegex(ValueError, "identity"):
            self.compute(post=status(strategy="staged"))

    def test_reject_geometry_change(self):
        with self.assertRaisesRegex(ValueError, "geometry"):
            self.compute(post=status().replace("0 65536 swapz", "0 65544 swapz"))

    def test_reject_counter_rollback(self):
        with self.assertRaisesRegex(ValueError, "decreased"):
            self.compute(post=status(logical_write=0))

    def test_reject_zero_denominator(self):
        with self.assertRaisesRegex(ValueError, "zero"):
            self.compute(post=status(physical_write=40960))

    def test_reject_fio_mismatch(self):
        with self.assertRaisesRegex(ValueError, "fio completed"):
            self.compute(expected=4096)

    def test_reject_lower_discrepancy(self):
        with self.assertRaisesRegex(ValueError, "differ by"):
            self.compute(lower_post="0 0 0 200")

    def test_reject_counter_invalid_gc(self):
        with self.assertRaisesRegex(ValueError, "GC write"):
            self.compute(post=status(logical_write=81920, physical_write=81920,
                                     gc_write=45056))

    def test_reject_bad_lower_stat(self):
        with self.assertRaisesRegex(ValueError, "four nonnegative"):
            self.compute(lower_pre="0 0 0")

    def test_reject_reverse_time(self):
        with self.assertRaisesRegex(ValueError, "nonpositive"):
            mod.compute(BASE, BASE, "0 0 0 0", "0 0 0 0", -1)

    def test_reject_bad_compression_counters(self):
        with self.assertRaisesRegex(ValueError, "disagree"):
            self.compute(post=status(logical_write=81920, physical_write=81920,
                                     compressed_payload=20000, compressed_pages=20))


if __name__ == "__main__":
    unittest.main()
