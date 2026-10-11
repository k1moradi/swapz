"""Rootless aligned-extent research benchmark; no kernel, swap, or device I/O.

Single-threaded ownership: the model owns immutable input bytes and submitted media.
Mapping changes occur only after successful, entire-extents writes. Garbage collection
is explicitly nonrecursive, and a victim is freed only after every survivor is
copied successfully. No assumptions about NAND writes or reader latencies.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from collections import defaultdict
import struct
import zlib

BLOCK_BYTES = 4096
SEGMENT_BLOCKS = 256
HEADER = struct.Struct('<IHH')
DESCRIPTOR = struct.Struct('<IHH')
MAGIC = 0x5A575053
VERSION = 2  # Experimental; not the in-kernel format.
MAX_RECORDS = 64
MAX_COMPRESSED_BYTES = 3568
EXTENT_CLASSES = (1, 2, 4, 16)
POLICIES = ('ordered4', 'bestfit4', 'fixed8', 'fixed16', 'fixed64', 'adaptive')


class MediaError(RuntimeError):
    """Fail-closed decoded metadata, payload checksum, or allocation error."""


@dataclass(frozen=True)
class Record:
    slot: int
    generation: int
    payload: bytes
    raw: bool = False

    def __post_init__(self):
        if not 0 <= self.slot < 2**32 or not 0 <= self.generation < 2**32:
            raise ValueError('slot/generation outside 32-bit metadata')
        if not isinstance(self.payload, bytes):
            raise TypeError('payload must be immutable bytes')
        if self.raw and len(self.payload) != BLOCK_BYTES:
            raise ValueError('raw fallback must store the original whole page')
        if not self.raw and not 0 < len(self.payload) <= MAX_COMPRESSED_BYTES:
            raise ValueError('invalid compressed payload length')


@dataclass(frozen=True)
class Mapping:
    extent_id: int
    slot: int
    generation: int
    offset: int
    length: int
    crc32: int
    raw: bool


@dataclass
class Segment:
    identifier: int
    state: str = 'free'
    used_blocks: int = 0
    extent_ids: list[int] = field(default_factory=list)


@dataclass(frozen=True)
class Extent:
    identifier: int
    segment_id: int
    starting_block: int
    image: bytes
    records: tuple[Record, ...]
    offsets: tuple[int, ...]

    @property
    def blocks(self) -> int:
        return len(self.image) // BLOCK_BYTES


def serialize(records: list[Record], block_count: int) -> tuple[bytes, tuple[int, ...]]:
    """Freeze descriptor count before assigning byte-exact payload offsets."""
    if block_count not in EXTENT_CLASSES or not records:
        raise ValueError('invalid block count or empty extent')
    if len(records) == 1 and records[0].raw:
        if block_count != 1:
            raise ValueError('raw pages consume one 4K block')
        return records[0].payload, (0,)
    if len(records) > MAX_RECORDS or any(record.raw for record in records):
        raise ValueError('invalid compressed-record count')
    image = bytearray(block_count * BLOCK_BYTES)
    HEADER.pack_into(image, 0, MAGIC, VERSION, len(records))
    offset = HEADER.size + len(records) * DESCRIPTOR.size
    offsets = []
    for index, record in enumerate(records):
        length = len(record.payload)
        if offset + length > len(image) or offset > 65535:
            raise ValueError('extent overflow')
        DESCRIPTOR.pack_into(image, HEADER.size + index * DESCRIPTOR.size,
                             record.slot, offset, length)
        image[offset:offset + length] = record.payload
        offsets.append(offset)
        offset += length
    return bytes(image), tuple(offsets)


def _can_fit(records: list[Record], record: Record, blocks: int) -> bool:
    return (len(records) < MAX_RECORDS and
            HEADER.size + (len(records) + 1) * DESCRIPTOR.size +
            sum(len(item.payload) for item in records) + len(record.payload)
            <= blocks * BLOCK_BYTES)


def _pack_fixed(records: list[Record], blocks: int, *, best_fit: bool) -> list[tuple[int, list[Record]]]:
    """Reorder only already-present records, never future window arrivals."""
    packed: list[tuple[int, list[Record]]] = []
    groups: list[list[Record]] = []
    ordered = sorted(records, key=lambda item: (-len(item.payload), item.slot)) if best_fit else records
    for record in ordered:
        if record.raw:
            packed.append((1, [record]))
            continue
        if best_fit:
            fits = [group for group in groups if _can_fit(group, record, blocks)]
            if fits:
                selected = max(fits, key=lambda group: sum(len(item.payload) for item in group)
                               + DESCRIPTOR.size * len(group))
                selected.append(record)
                continue
            groups.append([record])
        else:
            if not groups or not _can_fit(groups[-1], record, blocks):
                groups.append([record])
            else:
                groups[-1].append(record)
    packed.extend((blocks, group) for group in groups)
    return packed


def choose_pack(records: list[Record], policy: str, *, read_penalty_bytes: int = 0):
    """Select an extent class at the same bounded flush point for all policies.

    Adaptive minimizes full physical write bytes; ties prefer less spanning,
    then fewer 4K blocks. Read penalty is explicitly tunable rather than
    assuming a measured latency multiplier.
    """
    if policy not in POLICIES or read_penalty_bytes < 0:
        raise ValueError('unknown packing policy or negative read penalty')
    if not records:
        return []
    if policy == 'ordered4':
        return _pack_fixed(records, 1, best_fit=False)
    if policy == 'bestfit4':
        return _pack_fixed(records, 1, best_fit=True)
    fixed = {'fixed8': 2, 'fixed16': 4, 'fixed64': 16}
    candidates = (fixed[policy],) if policy in fixed else (1, 2, 4)
    scored = []
    for blocks in candidates:
        packed = _pack_fixed(records, blocks, best_fit=True)
        physical_bytes = sum(extent_blocks * BLOCK_BYTES for extent_blocks, _ in packed)
        extra_reads = 0
        for extent_blocks, group in packed:
            if group[0].raw:
                continue
            offset = HEADER.size + len(group) * DESCRIPTOR.size
            for item in group:
                extra_reads += (offset + len(item.payload) - 1) // BLOCK_BYTES - offset // BLOCK_BYTES
                offset += len(item.payload)
        scored.append((physical_bytes + extra_reads * read_penalty_bytes,
                       physical_bytes, extra_reads, blocks, packed))
    return min(scored, key=lambda value: value[:4])[-1]


class Replay:
    """A finite 1 MiB-segment media model with in-place overwrite *prohibited*.

    This is a single-threaded, committed-mapping simulator, not an asynchronous
    BIO or durable failure-recovery implementation. GC never recursively calls GC.
    """
    def __init__(self, policy: str, *, segment_count: int = 8, reserve_segments: int = 1,
                 window: int = 16, read_penalty_bytes: int = 0):
        if policy not in POLICIES or segment_count < 3 or not 0 < reserve_segments < segment_count - 1:
            raise ValueError('invalid policy or physical reserve')
        if not 0 < window <= 256 or read_penalty_bytes < 0:
            raise ValueError('invalid bounded window')
        self.policy, self.window, self.read_penalty_bytes = policy, window, read_penalty_bytes
        self.segments = [Segment(index) for index in range(segment_count)]
        self.reserve_segments = reserve_segments
        self.current_segment: int | None = None
        self.media: dict[int, Extent] = {}
        self.mappings: dict[int, Mapping] = {}
        self.latest_generation: dict[int, int] = {}
        self.staged: list[Record] = []
        self.next_extent_id = 1
        self.foreground_write_bytes = 0
        self.gc_write_bytes = 0
        self.foreground_submitted_bytes = 0
        self.gc_submitted_bytes = 0
        self.gc_read_blocks = 0
        self.completed_logical_bytes = 0
        self.failed_logical_writes = 0
        self.failed_gc_runs = 0
        self.gc_victims = 0
        self.upper_read_blocks = 0
        self.upper_reads = 0
        self.forced_flushes = 0

    def _free_segments(self) -> int:
        return sum(segment.state == 'free' for segment in self.segments)

    def _open_new_segment(self, *, gc: bool, excluded_segment: int | None = None) -> bool:
        free = next((segment for segment in self.segments
                     if segment.state == 'free' and segment.identifier != excluded_segment), None)
        if free is None or (not gc and self._free_segments() <= self.reserve_segments):
            return False
        if self.current_segment is not None:
            current = self.segments[self.current_segment]
            if current.state == 'open':
                current.state = 'closed'
        free.state = 'open'
        free.used_blocks = 0
        self.current_segment = free.identifier
        return True

    def _allocate(self, block_count: int, *, gc: bool = False,
                  excluded_segment: int | None = None) -> tuple[int, int] | None:
        assert block_count in EXTENT_CLASSES
        if self.current_segment is not None:
            current = self.segments[self.current_segment]
            if (current.state == 'open' and current.identifier != excluded_segment and
                    current.used_blocks + block_count <= SEGMENT_BLOCKS):
                start = current.used_blocks
                current.used_blocks += block_count
                return current.identifier, start
        if not self._open_new_segment(gc=gc, excluded_segment=excluded_segment):
            return None
        current = self.segments[self.current_segment]
        current.used_blocks = block_count
        return current.identifier, 0

    def _write_extent(self, records: list[Record], blocks: int, *, gc: bool,
                      excluded_segment: int | None = None, fail: bool = False,
                      partial_blocks: int = 0) -> Extent | None:
        if not 0 <= partial_blocks < blocks or (not fail and partial_blocks):
            raise ValueError('partial block completion requires failed entire extent')
        position = self._allocate(blocks, gc=gc, excluded_segment=excluded_segment)
        if position is None:
            return None
        image, offsets = serialize(records, blocks)
        identifier = self.next_extent_id
        self.next_extent_id += 1
        segment_id, start = position
        # Reserve/submit the full extent, but charge only physically completed
        # blocks on an explicitly torn lower write. Retain consumed addresses.
        completed_bytes = partial_blocks * BLOCK_BYTES if fail else len(image)
        if gc:
            self.gc_submitted_bytes += len(image)
            self.gc_write_bytes += completed_bytes
        else:
            self.foreground_submitted_bytes += len(image)
            self.foreground_write_bytes += completed_bytes
        if fail:
            return None
        extent = Extent(identifier, segment_id, start, image, tuple(records), offsets)
        self.media[identifier] = extent
        self.segments[segment_id].extent_ids.append(identifier)
        return extent

    @staticmethod
    def _mapping_pairs(extent: Extent) -> list[tuple[Record, Mapping]]:
        return [(record, Mapping(extent.identifier, record.slot, record.generation,
                                 offset, len(record.payload), zlib.crc32(record.payload), record.raw))
                for record, offset in zip(extent.records, extent.offsets)]

    def _read_mapping(self, mapping: Mapping) -> tuple[bytes, int]:
        extent = self.media.get(mapping.extent_id)
        if extent is None:
            raise MediaError('mapped extent missing')
        if mapping.raw:
            if (extent.blocks != 1 or len(extent.records) != 1 or
                    not extent.records[0].raw or mapping.offset or mapping.length != BLOCK_BYTES):
                raise MediaError('raw extent mismatch')
            payload = extent.image
            blocks = 1
        else:
            image = extent.image
            if len(image) < HEADER.size:
                raise MediaError('truncated header')
            magic, version, count = HEADER.unpack_from(image)
            if (magic, version, count) != (MAGIC, VERSION, len(extent.records)) or count > MAX_RECORDS:
                raise MediaError('invalid header')
            payload_start = HEADER.size + count * DESCRIPTOR.size
            if payload_start > len(image):
                raise MediaError('descriptor overflow')
            found = False
            intervals = []
            for index in range(count):
                slot, offset, length = DESCRIPTOR.unpack_from(image, HEADER.size + index * DESCRIPTOR.size)
                if not payload_start <= offset or not 0 < length <= MAX_COMPRESSED_BYTES or offset + length > len(image):
                    raise MediaError('out-of-bounds descriptor')
                intervals.append((offset, offset + length))
                found |= (slot, offset, length) == (mapping.slot, mapping.offset, mapping.length)
            intervals.sort()
            if any(end > next_start for (_, end), (next_start, _) in zip(intervals, intervals[1:])):
                raise MediaError('overlapping descriptors')
            if not found:
                raise MediaError('stale record descriptor')
            payload = image[mapping.offset:mapping.offset + mapping.length]
            payload_first = mapping.offset // BLOCK_BYTES
            payload_last = (mapping.offset + mapping.length - 1) // BLOCK_BYTES
            # Count blocks touched by metadata plus the requested payload (no cache assumption).
            blocks = len(set(range((payload_start + BLOCK_BYTES - 1) // BLOCK_BYTES)) |
                         set(range(payload_first, payload_last + 1)))
        if zlib.crc32(payload) != mapping.crc32:
            raise MediaError('payload checksum mismatch')
        return payload, blocks

    def read(self, slot: int) -> bytes | None:
        mapping = self.mappings.get(slot)
        if mapping is None:
            return None
        payload, blocks = self._read_mapping(mapping)
        self.upper_reads += 1
        self.upper_read_blocks += blocks
        return payload

    def stage(self, slot: int, payload: bytes, *, raw: bool = False) -> None:
        if len(self.staged) >= self.window:
            self.flush()
        generation = self.latest_generation.get(slot, 0) + 1
        # All in-window generations must be independently acknowledged; fail closed
        # instead of silently completing an overwritten pending BIO.
        if any(item.slot == slot for item in self.staged):
            raise ValueError('repeated slot within pending window requires BIO ownership model')
        record = Record(slot, generation, payload, raw)
        self.staged.append(record)
        self.latest_generation[slot] = generation
        if len(self.staged) == self.window:
            self.flush()

    def flush(self) -> bool:
        if not self.staged:
            return True
        self.forced_flushes += 1
