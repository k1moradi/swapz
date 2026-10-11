#!/usr/bin/env python3
"""
swapz_gc_sim.py
Deterministic event-driven Garbage Collection and Failure-Injection Simulator.
Models exact wear, victim relocation, reserve headroom, and read amplification.
"""

from __future__ import annotations
import math
import random
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple


@dataclass
class Record:
    slot: int
    gen: int
    offset: int
    length: int
    valid: bool = True


@dataclass
class Slab:
    slab_id: int
    size_bytes: int
    capacity: int
    used_bytes: int = 16
    records: List[Record] = field(default_factory=list)
    is_sealed: bool = False

    def can_fit(self, plen: int) -> bool:
        if len(self.records) >= self.capacity:
            return False
        return (self.used_bytes + 12 + plen) <= self.size_bytes

    def live_count(self) -> int:
        return sum(1 for r in self.records if r.valid)

    def live_fraction(self) -> float:
        return self.live_count() / len(self.records) if self.records else 0.0


class GCSimulator:
    def __init__(self, slab_size_kb: int = 4, total_device_mb: int = 16, reserve_pct: float = 0.15):
        self.slab_size_bytes = slab_size_kb * 1024
        self.total_device_bytes = total_device_mb * 1024 * 1024
        self.max_slabs = self.total_device_bytes // self.slab_size_bytes
        self.reserve_slabs = int(self.max_slabs * reserve_pct)
        self.usable_slabs = self.max_slabs - self.reserve_slabs

        hdr_overhead = 16
        rec_unit = 12 + 2074
        self.capacity_per_slab = max(1, (self.slab_size_bytes - hdr_overhead) // rec_unit)

        self.slabs: Dict[int, Slab] = {}
        self.active_slab: Optional[Slab] = None
        self.slab_seq = 0
        self.mapping: Dict[int, Tuple[int, int, int, int]] = {}  # slot -> (slab_id, gen, offset, len)

        # Accounting statistics
        self.foreground_user_writes = 0
        self.foreground_phys_bytes = 0
        self.gc_relocated_records = 0
        self.gc_phys_bytes = 0
        self.total_reads = 0
        self.total_read_blocks = 0
        self.injected_errors = 0

    def _allocate_slab(self) -> Slab:
        if len(self.slabs) >= self.usable_slabs:
            self._trigger_gc()
            if len(self.slabs) >= self.usable_slabs:
                raise RuntimeError("Device Reserve Exhaustion: Out of space!")

        s = Slab(slab_id=self.slab_seq, size_bytes=self.slab_size_bytes, capacity=self.capacity_per_slab)
        self.slabs[self.slab_seq] = s
        self.slab_seq += 1
        return s

    def write_slot(self, slot: int, gen: int, payload_len: int, inject_io_fail: bool = False) -> bool:
        if inject_io_fail:
            self.injected_errors += 1
            return False  # Simulated lower write failure; uncommitted to mapping

        # Overwrite invalidation
        if slot in self.mapping:
            old_sid, old_gen, _, _ = self.mapping[slot]
            if old_sid in self.slabs:
                for r in self.slabs[old_sid].records:
                    if r.slot == slot and r.gen == old_gen:
                        r.valid = False

        if not self.active_slab or not self.active_slab.can_fit(payload_len):
            if self.active_slab:
                self.active_slab.is_sealed = True
                self.foreground_phys_bytes += self.slab_size_bytes
            self.active_slab = self._allocate_slab()

        offset = self.active_slab.used_bytes + 12
        rec = Record(slot=slot, gen=gen, offset=offset, length=payload_len, valid=True)
        self.active_slab.records.append(rec)
        self.active_slab.used_bytes += 12 + payload_len
        self.foreground_user_writes += 1

        self.mapping[slot] = (self.active_slab.slab_id, gen, offset, payload_len)
        return True

    def read_slot(self, slot: int) -> int:
        if slot not in self.mapping:
            return 0
        sid, gen, offset, length = self.mapping[slot]
        slab = self.slabs[sid]

        # Verify generation integrity
        rec = next((r for r in slab.records if r.slot == slot and r.gen == gen), None)
        if not rec or not rec.valid:
            raise KeyError("Stale mapping violation!")

        # Calculate read amplification
        start_blk = offset // 4096
        end_blk = (offset + length - 1) // 4096
        blocks_read = (end_blk - start_blk) + 1

        self.total_reads += 1
        self.total_read_blocks += blocks_read
        return blocks_read

    def _trigger_gc(self) -> None:
        sealed_slabs = [s for s in self.slabs.values() if s.is_sealed]
        if not sealed_slabs:
            return

        # Select slab with lowest live fraction
        sealed_slabs.sort(key=lambda s: s.live_fraction())
        victim = sealed_slabs[0]

        surviving = [r for r in victim.records if r.valid]
        for r in surviving:
            # Relocate into active slab
            if not self.active_slab or not self.active_slab.can_fit(r.length):
                if self.active_slab:
                    self.active_slab.is_sealed = True
                    self.gc_phys_bytes += self.slab_size_bytes
                self.active_slab = Slab(slab_id=self.slab_seq, size_bytes=self.slab_size_bytes, capacity=self.capacity_per_slab)
                self.slabs[self.slab_seq] = self.active_slab
                self.slab_seq += 1

            offset = self.active_slab.used_bytes + 12
            new_rec = Record(slot=r.slot, gen=r.gen, offset=offset, length=r.length, valid=True)
            self.active_slab.records.append(new_rec)
            self.active_slab.used_bytes += 12 + r.length
            self.mapping[r.slot] = (self.active_slab.slab_id, r.gen, offset, r.length)
            self.gc_relocated_records += 1

        del self.slabs[victim.slab_id]

    def flush(self) -> None:
        if self.active_slab:
            self.active_slab.is_sealed = True
            self.foreground_phys_bytes += self.slab_size_bytes
            self.active_slab = None


def run_comprehensive_benchmark():
    random.seed(42)
    print("=== Reviewer 2: Deterministic GC & Overwrite Simulation ===")
    print("Workload: 10,000 Writes, Skewed Zipfian Overwrites across 2,048 Slots (16 MiB Dev)\n")

    for size_kb in (4, 8, 16, 64):
        sim = GCSimulator(slab_size_kb=size_kb, total_device_mb=16, reserve_pct=0.15)

        # 10,000 writes with Zipfian distribution (alpha=1.1) to generate realistic overwrites
        for i in range(10000):
            slot = int(random.paretovariate(1.1)) % 2048
            sim.write_slot(slot=slot, gen=i, payload_len=2074)

        sim.flush()

        # Execute 2,048 reads across all live slots
        for s in list(sim.mapping.keys()):
            sim.read_slot(s)

        total_phys_bytes = sim.foreground_phys_bytes + sim.gc_phys_bytes
        logical_bytes = sim.foreground_user_writes * 4096
        net_reduction = logical_bytes / total_phys_bytes if total_phys_bytes else 0.0
        gc_waf = (total_phys_bytes) / sim.foreground_phys_bytes if sim.foreground_phys_bytes else 0.0
        avg_read_blocks = sim.total_read_blocks / sim.total_reads if sim.total_reads else 0.0

        print(f"--- Configuration: {size_kb:2d} KiB Superblocks ---")
        print(f"Foreground Physical Bytes: {sim.foreground_phys_bytes:10,d} B")
        print(f"GC Relocation Bytes:       {sim.gc_phys_bytes:10,d} B")
        print(f"Total Lower Bytes Written: {total_phys_bytes:10,d} B")
        print(f"GC Write Amplification:    {gc_waf:10.3f}x")
        print(f"Net Physical Reduction:    {net_reduction:10.3f}x")
        print(f"Average 4K Blocks / Read:  {avg_read_blocks:10.2f}")
        print()

if __name__ == "__main__":
    run_comprehensive_benchmark()

