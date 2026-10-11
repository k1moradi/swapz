#!/usr/bin/env python3
"""
swapz_sizeclass_allocator.py
Runnable userspace model for block-native size-class storage.
Deterministic, rootless, zero external dependencies.
"""
import sys
import struct
import zlib

PAGE_SIZE = 4096
HEADER_SIZE = 32
DESC_SIZE = 16

class SuperblockConfig:
    def __init__(self, name, size_bytes, target_payload_capacity):
        self.name = name
        self.size_bytes = size_bytes
        self.capacity = target_payload_capacity

GEOMETRIES = {
    "4K": SuperblockConfig("4K", 4096, 4096 - HEADER_SIZE - DESC_SIZE),
    "8K": SuperblockConfig("8K", 8192, 8192 - HEADER_SIZE - (3 * DESC_SIZE)),
    "16K": SuperblockConfig("16K", 16384, 16384 - HEADER_SIZE - (7 * DESC_SIZE)),
    "64K": SuperblockConfig("64K", 65536, 65536 - HEADER_SIZE - (31 * DESC_SIZE)),
}

class Record:
    def __init__(self, logical_slot, generation, payload_bytes):
        self.logical_slot = logical_slot
        self.generation = generation
        self.payload = payload_bytes
        self.length = len(payload_bytes)

class Superblock:
    def __init__(self, geom: SuperblockConfig, extent_id: int, base_pba: int):
        self.geom = geom
        self.extent_id = extent_id
        self.base_pba = base_pba
        self.records = []
        self.current_payload_bytes = 0
        self.sealed = False

    def can_fit(self, record_len: int) -> bool:
        if self.sealed:
            return False
        new_desc_overhead = (len(self.records) + 1) * DESC_SIZE
        total_needed = HEADER_SIZE + new_desc_overhead + self.current_payload_bytes + record_len
        return total_needed <= self.geom.size_bytes

    def add_record(self, record: Record) -> int:
        offset = HEADER_SIZE + ((len(self.records) + 1) * DESC_SIZE) + self.current_payload_bytes
        self.records.append((record, offset))
        self.current_payload_bytes += record.length
        return offset

    def serialize(self) -> bytes:
        buf = bytearray(self.geom.size_bytes)
        hdr = struct.pack(
            "<4sHHQII8s",
            b"SWPZ",
            self.geom.size_bytes // 1024,
            1 if self.sealed else 0,
            self.extent_id,
            len(self.records),
            0, # CRC32 calculated later
            b"\x00" * 8
        )
        buf[0:32] = hdr
        desc_offset = HEADER_SIZE
        payload_start = HEADER_SIZE + (len(self.records) * DESC_SIZE)
        curr_p = payload_start

        for rec, _ in self.records:
            desc = struct.pack("<IQHH", rec.logical_slot, rec.generation, curr_p, rec.length)
            buf[desc_offset:desc_offset + DESC_SIZE] = desc
            desc_offset += DESC_SIZE
            buf[curr_p:curr_p + rec.length] = rec.payload
            curr_p += rec.length

        crc = zlib.crc32(buf[0:payload_start])
        struct.pack_into("<I", buf, 20, crc)
        return bytes(buf)

class SizeClassAllocator:
    def __init__(self, geom_key="8K", max_staged_slabs=4):
        self.geom = GEOMETRIES[geom_key]
        self.max_staged_slabs = max_staged_slabs
        self.active_slabs = []
        self.extent_counter = 0
        self.next_pba = 0
        self.mapping_table = {}  # slot -> (pba, offset, length, gen, state)
        self.total_physical_bytes_written = 0
        self.total_logical_bytes_received = 0

    def write_record(self, logical_slot: int, generation: int, payload: bytes):
        self.total_logical_bytes_received += PAGE_SIZE
        rec = Record(logical_slot, generation, payload)

        target_slab = None
        for slab in self.active_slabs:
            if slab.can_fit(rec.length):
                target_slab = slab
                break

        if target_slab is None:
            if len(self.active_slabs) >= self.max_staged_slabs:
                self.flush_oldest()
            self.extent_counter += 1
            target_slab = Superblock(self.geom, self.extent_counter, self.next_pba)
            self.next_pba += self.geom.size_bytes // 512
            self.active_slabs.append(target_slab)

        offset = target_slab.add_record(rec)
        # Staged in RAM
        self.mapping_table[logical_slot] = {
            "pba": target_slab.base_pba,
            "extent_bytes": self.geom.size_bytes,
            "offset": offset,
            "length": rec.length,
            "generation": generation,
            "state": "STAGED_RAM",
            "slab": target_slab
        }

    def flush_oldest(self):
        if not self.active_slabs:
            return
        slab = self.active_slabs.pop(0)
        self._commit_slab(slab)

    def flush_all(self):
        while self.active_slabs:
            self.flush_oldest()

    def _commit_slab(self, slab: Superblock):
        slab.sealed = True
        raw_data = slab.serialize()
        self.total_physical_bytes_written += len(raw_data)
        for rec, offset in slab.records:
            entry = self.mapping_table.get(rec.logical_slot)
            if entry and entry["generation"] == rec.generation and entry["slab"] == slab:
                entry["state"] = "COMMITTED_DISK"
                entry["slab"] = None

    def read_record(self, logical_slot: int) -> dict:
        entry = self.mapping_table.get(logical_slot)
        if not entry:
            return {"status": "MISS"}
        
        offset = entry["offset"]
        length = entry["length"]
        start_4k_block = offset // 4096
        end_4k_block = (offset + length - 1) // 4096
        blocks_needed = (end_4k_block - start_4k_block) + 1
        spans_boundary = start_4k_block != end_4k_block

        return {
            "status": "HIT",
            "state": entry["state"],
            "blocks_to_read": blocks_needed,
            "spans_boundary": spans_boundary,
            "length": length
        }

def run_tests():
    print("=== TEST 1: Packing Verification for ~2,072 B Records ===")
    test_payload = b"\xAA" * 2072

    for key, expected_rec in [("8K", 3), ("16K", 7), ("64K", 31)]:
        geom = GEOMETRIES[key]
        sb = Superblock(geom, 1, 0)
        packed = 0
        while sb.can_fit(len(test_payload)):
            sb.add_record(Record(packed, 1, test_payload))
            packed += 1
        reduction = (packed * PAGE_SIZE) / geom.size_bytes
        print(f"[{key} Extent] Records Packed: {packed}/{expected_rec} | Effective Reduction: {reduction:.3f}x")
        assert packed == expected_rec, f"Expected {expected_rec} records in {key}, got {packed}"

    print("\n=== TEST 2: Spanning Read Geometry in 8 KiB Superblock ===")
    alloc = SizeClassAllocator("8K", max_staged_slabs=1)
    for slot in range(3):
        alloc.write_record(slot, 1, b"\xBB" * 2072)
    alloc.flush_all()

    reads = [alloc.read_record(i) for i in range(3)]
    for i, r in enumerate(reads):
        print(f"Record {i}: Needs {r['blocks_to_read']} 4K block(s), Spans boundary: {r['spans_boundary']}")
    
    assert reads[0]["blocks_to_read"] == 1
    assert reads[1]["spans_boundary"] is True and reads[1]["blocks_to_read"] == 2
    assert reads[2]["blocks_to_read"] == 1
    print("Spanning read geometry correctly isolated.")

    print("\n=== TEST 3: Trace Comparison (8x2200 B followed by 8x1600 B) ===")
    trace = [2200] * 8 + [1600] * 8
    
    # 4K Sequential Allocator
    alloc_4k = SizeClassAllocator("4K", max_staged_slabs=1)
    for i, sz in enumerate(trace):
        alloc_4k.write_record(i, 1, b"\x00" * sz)
    alloc_4k.flush_all()
    
    # 8K Multi-Slab Allocator
    alloc_8k = SizeClassAllocator("8K", max_staged_slabs=2)
    for i, sz in enumerate(trace):
        alloc_8k.write_record(i, 1, b"\x00" * sz)
    alloc_8k.flush_all()

    print(f"4K Sequential Physical Bytes: {alloc_4k.total_physical_bytes_written} B (Containers: {alloc_4k.total_physical_bytes_written // 4096})")
    print(f"8K Multi-Slab Physical Bytes: {alloc_8k.total_physical_bytes_written} B (Containers: {alloc_8k.total_physical_bytes_written // 8192} x 8K)")
    print(f"Reduction vs 4K: {alloc_4k.total_physical_bytes_written / alloc_8k.total_physical_bytes_written:.2f}x")

if __name__ == "__main__":
    run_tests()

