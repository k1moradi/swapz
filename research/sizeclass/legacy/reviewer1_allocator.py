#!/usr/bin/env python3
"""
swapz_sizeclass_alloc.py
Rootless prototype of block-native size-class allocator for swapz.
Models 4 KiB, 8 KiB, 16 KiB, and 64 KiB superblocks with fullness tracking.
"""

from __future__ import annotations
import math
import struct
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Dict, List, Optional, Tuple


class Fullness(IntEnum):
    EMPTY = 0
    ALMOST_EMPTY = 1
    ALMOST_FULL = 2
    FULL = 3


@dataclass
class RecordDesc:
    slot: int
    generation: int
    offset: int
    length: int
    valid: bool = True


@dataclass
class Superblock:
    extent_id: int
    class_id: int
    block_size_bytes: int
    capacity_records: int
    used_bytes: int = 16  # 16-byte header
    records: List[RecordDesc] = field(default_factory=list)
    state: Fullness = Fullness.EMPTY

    def can_fit(self, payload_len: int) -> bool:
        if len(self.records) >= self.capacity_records:
            return False
        desc_overhead = 12
        return (self.used_bytes + desc_overhead + payload_len) <= self.block_size_bytes

    def add_record(self, slot: int, gen: int, payload_len: int) -> Tuple[int, int]:
        offset = self.used_bytes + 12
        desc = RecordDesc(slot=slot, generation=gen, offset=offset, length=payload_len)
        self.records.append(desc)
        self.used_bytes += 12 + payload_len
        self._update_fullness()
        return offset, len(self.records) - 1

    def _update_fullness(self) -> None:
        usage = self.used_bytes / self.block_size_bytes
        if len(self.records) >= self.capacity_records or usage >= 0.95:
            self.state = Fullness.FULL
        elif usage >= 0.50:
            self.state = Fullness.ALMOST_FULL
        elif usage > 0.0:
            self.state = Fullness.ALMOST_EMPTY
        else:
            self.state = Fullness.EMPTY

    def live_records_count(self) -> int:
        return sum(1 for r in self.records if r.valid)


class SizeClassAllocator:
    def __init__(self, superblock_size_kb: int = 4):
        self.sb_size_bytes = superblock_size_kb * 1024
        self.extent_counter = 0
        self.active_slabs: List[Superblock] = []
        self.sealed_slabs: List[Superblock] = []
        self.mapping_table: Dict[int, Tuple[int, int, int, int]] = {}  # slot -> (extent_id, gen, offset, len)

        # Capacity calculation based on ~2,072 B average payload
        hdr_overhead = 16
        rec_unit = 12 + 2072
        self.capacity_per_sb = max(1, (self.sb_size_bytes - hdr_overhead) // rec_unit)

    def allocate_and_pack(self, slot: int, gen: int, payload_len: int) -> Tuple[int, int]:
        # Invalidate old generation if slot is overwritten
        if slot in self.mapping_table:
            old_ext, old_gen, _, _ = self.mapping_table[slot]
            self._invalidate_record(old_ext, slot, old_gen)

        # Find almost-empty or almost-full slab
        target_slab: Optional[Superblock] = None
        for slab in self.active_slabs:
            if slab.can_fit(payload_len):
                target_slab = slab
                break

        if not target_slab:
            target_slab = Superblock(
                extent_id=self.extent_counter,
                class_id=0,
                block_size_bytes=self.sb_size_bytes,
                capacity_records=self.capacity_per_sb,
            )
            self.extent_counter += 1
            self.active_slabs.append(target_slab)

        offset, idx = target_slab.add_record(slot, gen, payload_len)
        self.mapping_table[slot] = (target_slab.extent_id, gen, offset, payload_len)

        if target_slab.state == Fullness.FULL:
            self.active_slabs.remove(target_slab)
            self.sealed_slabs.append(target_slab)

        return target_slab.extent_id, offset

    def flush_all(self) -> None:
        while self.active_slabs:
            slab = self.active_slabs.pop(0)
            self.sealed_slabs.append(slab)

    def _invalidate_record(self, extent_id: int, slot: int, gen: int) -> None:
        for slab in self.active_slabs + self.sealed_slabs:
            if slab.extent_id == extent_id:
                for r in slab.records:
                    if r.slot == slot and r.generation == gen:
                        r.valid = False
                        slab._update_fullness()
                        return

    def get_stats(self) -> Dict[str, float]:
        all_slabs = self.sealed_slabs + self.active_slabs
        total_physical_bytes = len(all_slabs) * self.sb_size_bytes
        total_records = sum(len(s.records) for s in all_slabs)
        live_records = sum(s.live_records_count() for s in all_slabs)
        logical_bytes = total_records * 4096
        gross_reduction = logical_bytes / total_physical_bytes if total_physical_bytes else 0.0

        return {
            "superblock_size_kb": self.sb_size_bytes / 1024,
            "total_superblocks": len(all_slabs),
            "total_physical_bytes": total_physical_bytes,
            "total_records": total_records,
            "live_records": live_records,
            "gross_reduction": gross_reduction,
            "records_per_superblock": total_records / len(all_slabs) if all_slabs else 0.0,
        }


def run_verification():
    print("=== Reviewer 1: Size-Class Allocator Geometry Verification ===")
    for size_kb in (4, 8, 16, 64):
        alloc = SizeClassAllocator(superblock_size_kb=size_kb)
        # Allocate uniform 2,072 B records up to capacity
        pages_to_test = 62
        for i in range(pages_to_test):
            alloc.allocate_and_pack(slot=i, gen=1, payload_len=2072)
        alloc.flush_all()
        stats = alloc.get_stats()
        print(f"[{size_kb:2d} KiB Superblock] Slabs: {stats['total_superblocks']:2.0f} | "
              f"Records/Slab: {stats['records_per_superblock']:4.2f} | "
              f"Gross Reduction: {stats['gross_reduction']:.3f}x")

if __name__ == "__main__":
    run_verification()

