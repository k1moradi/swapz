"""Rootless, deterministic swapz extent model; not a kernel implementation.

Disk authority is exclusively ``committed``. Payloads retained in ``pending``
are volatile, with a finite combined staged/in-flight RAM budget. No lower
write is treated as successful until ``complete(..., success=True)``.

No threads or actual BIOs: the caller serializes state transitions and supplies
completions. In a kernel port, protect these state transitions with one lock and
keep the completion callback's ownership until publication/release is finished.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import struct
import zlib
from typing import Literal

BLOCK_BYTES = 4096
EXTENT_BLOCK_COUNTS = (1, 2, 4, 16)
HEADER = struct.Struct('<4sHHQIIII')  # 32 bytes, little endian
DESCRIPTOR = struct.Struct('<QQIIII')  # 32 bytes: slot, generation, offset, len, crc, flags
MAGIC = b'SZSC'
VERSION = 1
RAW_PAGE_BYTES = BLOCK_BYTES


class AllocatorError(RuntimeError):
    """Invalid allocation, mapping or write transition."""


class Backpressure(AllocatorError):
    """A bounded buffer/in-flight limit prevents accepting/submitting work."""


class CorruptExtent(AllocatorError):
    """Committed bytes cannot be safely interpreted."""


@dataclass(frozen=True)
class Descriptor:
    slot: int
    generation: int
    offset: int
    length: int
    checksum: int


@dataclass(frozen=True)
class Mapping:
    extent_id: int
    generation: int
    offset: int
    length: int
    checksum: int
    raw: bool


@dataclass
class PendingRecord:
    slot: int
    generation: int
    payload: bytes
    raw: bool = False
    state: Literal['STAGED', 'IN_FLIGHT', 'SUPERSEDED', 'FAILED', 'COMMITTED'] = 'STAGED'


@dataclass
class Extent:
    extent_id: int
    block_count: int
    records: list[PendingRecord] = field(default_factory=list)
    state: Literal['STAGED', 'IN_FLIGHT'] = 'STAGED'
    image: bytes | None = None
    submitted_records: tuple[PendingRecord, ...] = ()

    @property
    def byte_length(self) -> int:
        return BLOCK_BYTES * self.block_count

    def can_fit(self, length: int, replacing: PendingRecord | None = None) -> bool:
        if self.state != 'STAGED' or length <= 0 or length >= BLOCK_BYTES:
            return False
        live = [record for record in self.records
                if record.state == 'STAGED' and record is not replacing]
        return (HEADER.size + (len(live) + 1) * DESCRIPTOR.size
                + sum(len(record.payload) for record in live) + length <= self.byte_length)


def serialize_extent(extent: Extent) -> tuple[bytes, dict[tuple[int, int], Descriptor]]:
    """Final offsets are assigned only after the descriptor count is frozen.

    The zeroed four-byte header CRC field is at offset 24. Metadata CRC covers
    header + descriptor table; each descriptor separately checks its payload.
    All padding bytes are zero and every physical image is 4 KiB aligned.
    """
    if extent.block_count not in EXTENT_BLOCK_COUNTS:
        raise ValueError('unsupported extent class')
    if extent.state != 'STAGED':
        raise AllocatorError('extent is already submitted')
    records = [record for record in extent.records if record.state == 'STAGED']
    if not records or any(record.raw for record in records):
        raise AllocatorError('empty or raw extent cannot use compressed layout')
    descriptor_end = HEADER.size + len(records) * DESCRIPTOR.size
    if descriptor_end + sum(len(record.payload) for record in records) > extent.byte_length:
        raise AllocatorError('extent overflow')
    image = bytearray(extent.byte_length)
    HEADER.pack_into(image, 0, MAGIC, VERSION, HEADER.size, extent.extent_id,
                     len(records), extent.byte_length, 0, 0)
    payload_offset = descriptor_end
    descriptors: dict[tuple[int, int], Descriptor] = {}
    slots: set[int] = set()
    for index, record in enumerate(records):
        if record.slot in slots or not 0 <= record.slot < 2**64 or not 0 <= record.generation < 2**64:
            raise AllocatorError('invalid or duplicate record identity')
        slots.add(record.slot)
        payload_length = len(record.payload)
        checksum = zlib.crc32(record.payload)
        DESCRIPTOR.pack_into(image, HEADER.size + index * DESCRIPTOR.size,
                             record.slot, record.generation, payload_offset,
                             payload_length, checksum, 0)
        image[payload_offset:payload_offset + payload_length] = record.payload
        descriptors[(record.slot, record.generation)] = Descriptor(
            record.slot, record.generation, payload_offset, payload_length, checksum)
        payload_offset += payload_length
    header_checksum = zlib.crc32(image[:descriptor_end])
    struct.pack_into('<I', image, 24, header_checksum)
    return bytes(image), descriptors


def parse_extent(image: bytes, expected_extent_id: int | None = None, *,
                 validate_all_payloads: bool = True) -> dict[tuple[int, int], Descriptor]:
    """Validate extent metadata, optionally all record bytes at completion.

    A read with cached descriptors checks only its requested payload; it does
    not issue modeled physical reads for every sibling merely to verify CRCs.
    """
    if len(image) < HEADER.size or len(image) // BLOCK_BYTES not in EXTENT_BLOCK_COUNTS or len(image) % BLOCK_BYTES:
        raise CorruptExtent('unaligned or unsupported image length')
    magic, version, header_size, extent_id, count, image_length, checksum, flags = HEADER.unpack_from(image)
    if (magic != MAGIC or version != VERSION or header_size != HEADER.size or flags
            or image_length != len(image) or count == 0
            or expected_extent_id is not None and extent_id != expected_extent_id):
        raise CorruptExtent('invalid extent header')
    descriptor_end = HEADER.size + count * DESCRIPTOR.size
    if descriptor_end > len(image):
        raise CorruptExtent('descriptor table exceeds extent')
    metadata = bytearray(image[:descriptor_end])
    struct.pack_into('<I', metadata, 24, 0)
    if zlib.crc32(metadata) != checksum:
        raise CorruptExtent('metadata checksum mismatch')
    descriptors: dict[tuple[int, int], Descriptor] = {}
    slots: set[int] = set()
    previous_end = descriptor_end
    for index in range(count):
        slot, generation, offset, length, payload_crc, record_flags = DESCRIPTOR.unpack_from(
            image, HEADER.size + index * DESCRIPTOR.size)
        if (slot in slots or record_flags or not 0 < length < BLOCK_BYTES
                or offset != previous_end or offset + length > len(image)):
            raise CorruptExtent('invalid descriptor offsets or identities')
        slots.add(slot)
        if validate_all_payloads and zlib.crc32(image[offset:offset + length]) != payload_crc:
            raise CorruptExtent('record payload checksum mismatch')
        descriptors[(slot, generation)] = Descriptor(slot, generation, offset, length, payload_crc)
        previous_end = offset + length
    return descriptors


@dataclass(frozen=True)
class ReadResult:
    payload: bytes
    generation: int
    payload_blocks: int
    metadata_blocks: int

    @property
    def total_read_blocks(self) -> int:
        return self.payload_blocks + self.metadata_blocks


class SizeClassAllocator:
    """Bounded single-threaded IO-completion state machine.

    A caller submits work with ``flush`` and explicitly delivers completion;
    ``stage`` is not acknowledgement of durable/committed output. The model
    has no crash recovery or real device persistence. Writes to a distinct new
    extent ID cannot corrupt previously committed images on torn completion.
    """

    def __init__(self, block_count: int = 2, *, max_buffered_bytes: int = 256 * 1024,
                 max_buffered_records: int = 128, max_staged_extents: int = 4,
                 max_inflight_extents: int = 4, flush_deadline: int = 16):
        if block_count not in EXTENT_BLOCK_COUNTS:
            raise ValueError('block_count must be 1, 2, 4 or 16')
        if (max_buffered_bytes < BLOCK_BYTES or max_buffered_records < 1
                or max_staged_extents < 1 or max_inflight_extents < 1
                or flush_deadline < 1):
            raise ValueError('invalid resource bounds')
        self.block_count = block_count
        self.max_buffered_bytes = max_buffered_bytes
        self.max_buffered_records = max_buffered_records
        self.max_staged_extents = max_staged_extents
        self.max_inflight_extents = max_inflight_extents
        self.flush_deadline = flush_deadline
        self.now = 0
        self.oldest_staged_tick: int | None = None
        self.next_extent_id = 1
        self.staged: list[Extent] = []
        self.inflight: dict[int, Extent] = {}
        self.pending: dict[int, PendingRecord] = {}
        self.committed: dict[int, Mapping] = {}
        self.media: dict[int, bytes] = {}
        self.highest_generation: dict[int, int] = {}
        self.submitted_physical_bytes = 0
        self.completed_physical_bytes = 0
        self.partial_physical_bytes = 0
        self.failed_operations = 0
        self.completed_logical_bytes = 0

    def _live_pending(self) -> list[PendingRecord]:
        return [record for extent in (*self.staged, *self.inflight.values())
                for record in extent.records if record.state in ('STAGED', 'IN_FLIGHT')
                or (extent.state == 'IN_FLIGHT' and record in extent.submitted_records)]

    def _new_extent(self, block_count: int) -> Extent:
        extent = Extent(self.next_extent_id, block_count)
        self.next_extent_id += 1
        self.staged.append(extent)
        self.oldest_staged_tick = self.now if self.oldest_staged_tick is None else self.oldest_staged_tick
        return extent

    def stage(self, slot: int, generation: int, payload: bytes, *, raw_page: bytes | None = None) -> None:
        """Stage one record; reject if an explicit finite RAM budget is exhausted.

        ``raw_page`` must contain the actual 4096-byte uncompressed page if
        compressed bytes cannot fit. Fabricating a raw page by padding an LZ
        blob would make readback incorrect and is prohibited.
        """
        if not 0 <= slot < 2**64 or not 0 <= generation < 2**64:
            raise ValueError('slot/generation out of 64-bit range')
        if generation <= self.highest_generation.get(slot, -1):
            raise AllocatorError('stale or duplicate generation')
        record_payload = bytes(payload)
        if not 0 < len(record_payload) <= BLOCK_BYTES:
            raise ValueError('payload must have 1..4096 bytes')
        raw = len(record_payload) == BLOCK_BYTES or len(record_payload) > BLOCK_BYTES - HEADER.size - DESCRIPTOR.size
        if raw:
            if len(record_payload) < BLOCK_BYTES:
                if raw_page is None or len(raw_page) != BLOCK_BYTES:
                    raise AllocatorError('raw fallback requires the original 4096-byte page')
                record_payload = bytes(raw_page)
        elif raw_page is not None and len(raw_page) != BLOCK_BYTES:
            raise ValueError('raw_page must be a full page')

        replaced = self.pending.get(slot)
        live_records = self._live_pending()
        outstanding_bytes = sum(len(record.payload) for record in live_records)
        old_staged_bytes = len(replaced.payload) if replaced and replaced.state == 'STAGED' else 0
        old_staged_count = 1 if old_staged_bytes else 0
        if (outstanding_bytes - old_staged_bytes + len(record_payload) > self.max_buffered_bytes
                or len(live_records) - old_staged_count + 1 > self.max_buffered_records):
            raise Backpressure('bounded pending RAM exhausted')
        target: Extent | None = None
        if not raw:
            for extent in self.staged:
                if extent.block_count == self.block_count and extent.can_fit(len(record_payload), replacing=replaced):
                    target = extent
                    break
        replaced_extent = next((extent for extent in self.staged
                                if replaced is not None and replaced.state == 'STAGED'
                                and any(record is replaced for record in extent.records)), None)
        empty_after_replacement = (replaced_extent is not None and replaced_extent is not target
                                   and len(replaced_extent.records) == 1)
        staged_count_after_replacement = len(self.staged) - int(empty_after_replacement)
        if target is None and staged_count_after_replacement >= self.max_staged_extents:
            raise Backpressure('bounded staged extent window exhausted: flush and complete')
        if replaced is not None:
            if replaced_extent is not None:
                replaced_extent.records.remove(replaced)
                if not replaced_extent.records and replaced_extent is not target:
                    self.staged.remove(replaced_extent)
            replaced.state = 'SUPERSEDED'
        if target is None:
            target = self._new_extent(1 if raw else self.block_count)
        new_record = PendingRecord(slot, generation, record_payload, raw)
        target.records.append(new_record)
        self.pending[slot] = new_record
        self.highest_generation[slot] = generation

    def tick(self, count: int = 1) -> list[int]:
        """Advance a logical clock; flush once the oldest staged deadline expires."""
        if count < 0:
            raise ValueError('negative ticks')
        self.now += count
        if self.oldest_staged_tick is not None and self.now - self.oldest_staged_tick >= self.flush_deadline:
            return self.flush()
        return []

    def flush(self) -> list[int]:
        """Submit sealed images without publishing disk authority.

        Submission is all-or-nothing with respect to available in-flight slots.
        Empty fully superseded slabs require no lower write.
        """
        candidates = [extent for extent in self.staged
                      if any(record.state == 'STAGED' for record in extent.records)]
        if len(candidates) + len(self.inflight) > self.max_inflight_extents:
            raise Backpressure('in-flight extent limit')
        submitted: list[int] = []
        for extent in self.staged:
            live = [record for record in extent.records if record.state == 'STAGED']
            if not live:
                continue
            if any(record.raw for record in live):
                if len(live) != 1 or not live[0].raw or len(live[0].payload) != BLOCK_BYTES:
                    raise AllocatorError('malformed raw extent')
                image = live[0].payload
            else:
                image, _ = serialize_extent(extent)
            extent.image = image
            extent.submitted_records = tuple(live)
            extent.state = 'IN_FLIGHT'
            for record in live:
                record.state = 'IN_FLIGHT'
            self.inflight[extent.extent_id] = extent
            self.submitted_physical_bytes += len(image)
            submitted.append(extent.extent_id)
        self.staged.clear()
        self.oldest_staged_tick = None
        return submitted

    def complete(self, extent_id: int, *, success: bool,
                 partial_blocks: int = 0) -> list[tuple[int, int]]:
        """Complete whole lower extent or drop it; never publish a torn write.

        Partial writes model only whole 4K sub-blocks; individual lower BIO
        submission/completion accounting and GC are left to the GC reviewer.
        """
        if extent_id not in self.inflight:
            raise AllocatorError('extent is not in flight')
        extent = self.inflight[extent_id]
        if not 0 <= partial_blocks < extent.block_count:
            raise ValueError('partial_blocks must be below extent block count')
        if success and partial_blocks:
            raise ValueError('successful writes cannot be partial')
        assert extent.image is not None and extent.submitted_records
        submitted_records = extent.submitted_records
        if success:
            if submitted_records[0].raw:
                descriptors = {(submitted_records[0].slot, submitted_records[0].generation): Descriptor(
                    submitted_records[0].slot, submitted_records[0].generation, 0,
                    BLOCK_BYTES, zlib.crc32(extent.image))}
            else:
                descriptors = parse_extent(extent.image, extent.extent_id)
        else:
            descriptors = {}
        del self.inflight[extent_id]
        if success:
            self.media[extent_id] = extent.image
            self.completed_physical_bytes += len(extent.image)
        else:
            self.failed_operations += 1
            self.partial_physical_bytes += partial_blocks * BLOCK_BYTES
        published = []
        for record in submitted_records:
            if self.pending.get(record.slot) is not record:
                record.state = 'SUPERSEDED'
            elif success and record.generation > self.committed.get(
                    record.slot, Mapping(0, -1, 0, 0, 0, False)).generation:
                descriptor = descriptors[(record.slot, record.generation)]
                self.committed[record.slot] = Mapping(extent_id, record.generation,
                    descriptor.offset, descriptor.length, descriptor.checksum, record.raw)
                record.state = 'COMMITTED'
                del self.pending[record.slot]
                self.completed_logical_bytes += BLOCK_BYTES
                published.append((record.slot, record.generation))
            else:
                record.state = 'FAILED' if not success else 'SUPERSEDED'
                self.pending.pop(record.slot, None)
        return published

    def read(self, slot: int, *, metadata_cached: bool = True) -> ReadResult | None:
        """Read only committed storage and report actual touched 4K blocks.

        On invalid metadata/CRC a read raises CorruptExtent (fail closed).
        With metadata_cached=False, header/descriptor block 0 is added only
        if the payload itself does not touch it.
        """
        mapping = self.committed.get(slot)
        if mapping is None:
            return None
        image = self.media.get(mapping.extent_id)
        if image is None:
            raise CorruptExtent('committed extent missing')
        if mapping.raw:
            if (mapping.offset != 0 or mapping.length != BLOCK_BYTES
                    or len(image) != BLOCK_BYTES or zlib.crc32(image) != mapping.checksum):
                raise CorruptExtent('corrupt raw mapping')
        else:
            descriptor = parse_extent(image, mapping.extent_id,
                                      validate_all_payloads=False).get((slot, mapping.generation))
            if descriptor is None or (descriptor.offset, descriptor.length, descriptor.checksum) != (
                    mapping.offset, mapping.length, mapping.checksum):
                raise CorruptExtent('stale or corrupted mapping')
        if mapping.offset + mapping.length > len(image) or mapping.length < 1:
            raise CorruptExtent('out-of-bounds mapping')
        if zlib.crc32(image[mapping.offset:mapping.offset + mapping.length]) != mapping.checksum:
            raise CorruptExtent('record payload checksum mismatch')
        first_block = mapping.offset // BLOCK_BYTES
        last_block = (mapping.offset + mapping.length - 1) // BLOCK_BYTES
        payload_blocks = last_block - first_block + 1
        metadata_blocks = int(not metadata_cached and not mapping.raw and first_block != 0)
        return ReadResult(image[mapping.offset:mapping.offset + mapping.length],
                          mapping.generation, payload_blocks, metadata_blocks)


def pack_windows(payload_sizes: list[int], flush_sizes: list[int], *, strategy: str,
                 block_count: int = 1) -> list[list[int]]:
    """One-window bounded causal best-fit vs source-ordered repack.

    flush_sizes are externally given record counts at identical flush points;
    every window closes its bins. ``best_fit`` can reorder only records that
    have already arrived in that window. No future trace is consulted.
    """
    if block_count not in EXTENT_BLOCK_COUNTS or strategy not in ('ordered', 'best_fit'):
        raise ValueError('invalid class or packing strategy')
    if any(not 0 < size < BLOCK_BYTES for size in payload_sizes):
        raise ValueError('compressed payload length out of range')
    if any(size <= 0 for size in flush_sizes) or sum(flush_sizes) != len(payload_sizes):
        raise ValueError('flush_sizes must cover trace exactly')
    result: list[list[int]] = []
    position = 0
    capacity = block_count * BLOCK_BYTES
    for count in flush_sizes:
        values = payload_sizes[position:position + count]
        position += count
        if strategy == 'best_fit':
            values = sorted(values, reverse=True)
        bins: list[list[int]] = []
        for payload_size in values:
            feasible = [index for index, values_in_bin in enumerate(bins)
                        if HEADER.size + (len(values_in_bin) + 1) * DESCRIPTOR.size
                        + sum(values_in_bin) + payload_size <= capacity]
            if strategy == 'ordered':
                selected = len(bins) - 1 if feasible and feasible[-1] == len(bins) - 1 else None
            else:
                selected = max(feasible, key=lambda index: sum(bins[index]) +
                               DESCRIPTOR.size * len(bins[index])) if feasible else None
            if selected is None:
                if HEADER.size + DESCRIPTOR.size + payload_size > capacity:
                    raise ValueError('record cannot fit extent; raw fallback required')
                bins.append([payload_size])
            else:
                bins[selected].append(payload_size)
        result.extend(bins)
    return result
