"""Research-only little-endian extent wire codec; not the kernel V2.2 format."""
import struct

BLOCK_BYTES = 4096
HEADER = struct.Struct('<IHH')
DESCRIPTOR = struct.Struct('<IHH')
MAGIC, VERSION = 0x53575A53, 1
MAX_COMPRESSED_BYTES, MAX_PACKED_RECORDS = 3568, 64
SUPPORTED_BLOCK_COUNTS = (1, 2, 4, 16)


class CorruptExtentError(ValueError):
    """Invalid or mismatched committed extent metadata."""


def serialize(records, block_count):
    """Return immutable extent bytes and exact payload offsets for the records."""
    if len(records) == 1 and records[0].raw:
        if len(records[0].payload) != BLOCK_BYTES:
            raise ValueError('raw extent must contain exactly one whole page')
        return records[0].payload, (0,)
    if not 0 < len(records) <= MAX_PACKED_RECORDS or any(record.raw for record in records):
        raise ValueError('invalid compressed record group')
    content = bytearray(block_count * BLOCK_BYTES)
    HEADER.pack_into(content, 0, MAGIC, VERSION, len(records))
    offset = HEADER.size + len(records) * DESCRIPTOR.size
    offsets = []
    for index, record in enumerate(records):
        length = len(record.payload)
        if not 0 < length <= MAX_COMPRESSED_BYTES or offset > 65535 or offset + length > len(content):
            raise ValueError('record does not fit encoded extent')
        DESCRIPTOR.pack_into(content, HEADER.size + index * DESCRIPTOR.size,
                             record.logical_page, offset, length)
        content[offset:offset + length] = record.payload
        offsets.append(offset)
        offset += length
    return bytes(content), tuple(offsets)


def read_record(content, mapping):
    """Validate all descriptors before reading one mapped payload; fail closed."""
    if mapping.raw:
        if len(content) != BLOCK_BYTES or mapping.offset != 0 or mapping.length != BLOCK_BYTES:
            raise CorruptExtentError('invalid raw extent')
        return content, 1
    if len(content) not in tuple(blocks * BLOCK_BYTES for blocks in SUPPORTED_BLOCK_COUNTS):
        raise CorruptExtentError('invalid extent size')
    magic, version, count = HEADER.unpack_from(content)
    if (magic, version) != (MAGIC, VERSION) or not 0 < count <= MAX_PACKED_RECORDS:
        raise CorruptExtentError('invalid container header')
    data_start = HEADER.size + count * DESCRIPTOR.size
    if data_start > len(content):
        raise CorruptExtentError('oversized descriptor table')
    intervals, found = [], False
    for index in range(count):
        logical_page, offset, length = DESCRIPTOR.unpack_from(
            content, HEADER.size + index * DESCRIPTOR.size)
        if not data_start <= offset or not 0 < length <= MAX_COMPRESSED_BYTES or offset + length > len(content):
            raise CorruptExtentError('invalid descriptor bounds')
        intervals.append((offset, offset + length))
        found |= (logical_page, offset, length) == (mapping.logical_page, mapping.offset, mapping.length)
    intervals.sort()
    if not found or any(end > next_start for (_, end), (next_start, _) in zip(intervals, intervals[1:])):
        raise CorruptExtentError('overlap or mapping mismatch')
    first = mapping.offset // BLOCK_BYTES
    last = (mapping.offset + mapping.length - 1) // BLOCK_BYTES
    return content[mapping.offset:mapping.offset + mapping.length], last - first + 1
