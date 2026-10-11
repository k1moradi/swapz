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
