#!/usr/bin/env python3
"""
swapz_gc_simulator.py
Deterministic, event-driven GC and failure simulation for swapz.
Evaluates 4K, 8K, 16K, and 64K layouts under realistic overwrite pressure.
"""
import sys
import random
from collections import defaultdict

SEGMENT_SIZE = 2 * 1024 * 1024  # 2 MiB physical segments
TOTAL_SEGMENTS = 64             # 128 MiB total storage
PAGE_SIZE = 4096

class PhysicalExtent:
    def __init__(self, extent_id, size_bytes, segment_id):
        self.extent_id = extent_id
        self.size_bytes = size_bytes
        self.segment_id = segment_id
        self.records = {} # slot -> (generation, length, offset)
        self.live_bytes = 0

class Segment:
    def __init__(self, segment_id):
        self.segment_id = segment_id
        self.extents = []
        self.free_bytes = SEGMENT_SIZE
        self.is_clean = True

    @property
    def live_bytes(self):
        return sum(ext.live_bytes for ext in self.extents)

    @property
    def live_fraction(self):
        allocated = SEGMENT_SIZE - self.free_bytes
        return self.live_bytes / allocated if allocated > 0 else 0.0

class GCSimulator:
    def __init__(self, extent_size=8192, seed=42):
        random.seed(seed)
        self.extent_size = extent_size
        self.segments = [Segment(i) for i in range(TOTAL_SEGMENTS)]
        self.free_segments = list(range(TOTAL_SEGMENTS))
        self.active_segment_id = self.free_segments.pop(0)
        self.segments[self.active_segment_id].is_clean = False
        
        self.mappings = {} # slot -> (extent, gen, length, offset)
        self.extent_counter = 0
        
        # Statistics
        self.logical_bytes_in = 0
        self.foreground_bytes_written = 0
        self.gc_relocation_bytes_written = 0
        self.total_read_blocks_issued = 0
        self.total_reads_serviced = 0
        self.stale_race_preventions = 0
        self.failed_writes_handled = 0

    def _allocate_extent(self, is_gc=False) -> PhysicalExtent:
        seg = self.segments[self.active_segment_id]
        if seg.free_bytes < self.extent_size:
            self._rotate_segment()
            seg = self.segments[self.active_segment_id]

        self.extent_counter += 1
        ext = PhysicalExtent(self.extent_counter, self.extent_size, self.active_segment_id)
        seg.extents.append(ext)
        seg.free_bytes -= self.extent_size
        
        if is_gc:
            self.gc_relocation_bytes_written += self.extent_size
        else:
            self.foreground_bytes_written += self.extent_size
        return ext

    def _rotate_segment(self):
        # Trigger GC if free segments drop below 15% watermark
        if len(self.free_segments) <= max(2, int(TOTAL_SEGMENTS * 0.15)):
            self._run_gc_cycle()

        if not self.free_segments:
            raise RuntimeError("Out of Physical Storage: Reserve Exhaustion")

        self.active_segment_id = self.free_segments.pop(0)
        self.segments[self.active_segment_id].is_clean = False

    def write_page(self, slot: int, payload_len: int, fail_injection=False) -> bool:
        self.logical_bytes_in += PAGE_SIZE
        old_mapping = self.mappings.get(slot)
        new_gen = (old_mapping[1] + 1) if old_mapping else 1

        if fail_injection:
            self.failed_writes_handled += 1
            # Lower I/O failure: mapping untouched
            return False

        ext = self._allocate_extent(is_gc=False)
        ext.records[slot] = (new_gen, payload_len, 32)
        ext.live_bytes += payload_len

        # Invalidate older generation in old extent
        if old_mapping:
            old_ext, old_gen, old_len, _ = old_mapping
            if old_gen < new_gen:
                old_ext.live_bytes -= old_len
                del old_ext.records[slot]

        self.mappings[slot] = (ext, new_gen, payload_len, 32)
        return True

    def read_page(self, slot: int) -> int:
        entry = self.mappings.get(slot)
        if not entry:
            return 0
        ext, gen, length, offset = entry
        start_4k = offset // 4096
        end_4k = (offset + length - 1) // 4096
        blocks = (end_4k - start_4k) + 1
        self.total_read_blocks_issued += blocks
        self.total_reads_serviced += 1
        return blocks

    def _run_gc_cycle(self):
        # Greedy victim selection: Find allocated segment with lowest live bytes
        candidates = [s for s in self.segments if not s.is_clean and s.segment_id != self.active_segment_id]
        if not candidates:
            return
        
        victim = min(candidates, key=lambda s: s.live_bytes)
        
        # Relocate surviving records
        for ext in victim.extents:
            for slot, (gen, length, offset) in list(ext.records.items()):
                current = self.mappings.get(slot)
                # Generation Conflict Check: Drop stale records
                if not current or current[1] != gen:
                    self.stale_race_preventions += 1
                    continue

                # Relocate to active write stream
                new_ext = self._allocate_extent(is_gc=True)
                new_ext.records[slot] = (gen, length, offset)
                new_ext.live_bytes += length
                self.mappings[slot] = (new_ext, gen, length, offset)

        # Reclaim victim segment
        victim.extents.clear()
        victim.free_bytes = SEGMENT_SIZE
        victim.is_clean = True
        self.free_segments.append(victim.segment_id)

def run_simulation_suite():
    workloads = [
        ("Uniform 2,072 B (50% fio)", lambda: 2072),
        ("Bimodal (50% 2,200B / 50% 1,600B)", lambda: 2200 if random.random() < 0.5 else 1600),
        ("Actual PR #31 Distribution", lambda: int(random.gauss(2072, 85))),
    ]

    print(f"{'Layout':<8} | {'Workload':<32} | {'Gross Red.':<10} | {'GC Reloc.':<12} | {'Net Red.':<9} | {'Read Amp.'}")
    print("-" * 88)

    for layout_name, ext_size in [("4 KiB", 4096), ("8 KiB", 8192), ("16 KiB", 16384), ("64 KiB", 65536)]:
        for w_name, gen_func in workloads:
            sim = GCSimulator(extent_size=ext_size, seed=12345)
            
            # Hot/Cold Skew Overwrite Trace: 8,000 writes across 2,000 slots (80/20 skew)
            slots = [i for i in range(2000)]
            for step in range(8000):
                slot = random.choice(slots[:400]) if random.random() < 0.8 else random.choice(slots[400:])
                plen = gen_func()
                # Periodic failure injection (1 in 500)
                fail = (step % 500 == 0)
                sim.write_page(slot, plen, fail_injection=fail)

            # Sample 1,000 cold reads
            for _ in range(1000):
                sim.read_page(random.choice(slots))

            gross_red = sim.logical_bytes_in / sim.foreground_bytes_written
            total_physical = sim.foreground_bytes_written + sim.gc_relocation_bytes_written
            net_red = sim.logical_bytes_in / total_physical
            read_amp = sim.total_read_blocks_issued / sim.total_reads_serviced

            print(f"{layout_name:<8} | {w_name:<32} | {gross_red:>8.3f}x | {sim.gc_relocation_bytes_written // 1024:>9} KB | {net_red:>7.3f}x | {read_amp:>8.2f} blk")

if __name__ == "__main__":
    run_simulation_suite()

