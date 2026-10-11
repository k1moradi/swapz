"""Single-worker rootless allocator: bounded RAM, explicit I/O completion authority.

No GC, crash consistency, concurrency or real storage I/O. The caller holds tickets;
this model owns immutable bytes and retains spent extents until exhaustion.
"""
from dataclasses import dataclass
from wire import (BLOCK_BYTES, HEADER, DESCRIPTOR, MAX_COMPRESSED_BYTES,
                  MAX_PACKED_RECORDS, SUPPORTED_BLOCK_COUNTS, CorruptExtentError,
                  serialize, read_record)


@dataclass
class WriteTicket:
    identifier: int
    logical_page: int
    generation: int
    payload: bytes
    raw: bool
    state: str = 'staged'
    upper_completed: bool = False


@dataclass(frozen=True)
class RecordLocation:
    logical_page: int
    generation: int
    extent_identifier: int
    offset: int
    length: int
    raw: bool


@dataclass(frozen=True)
class SubmittedExtent:
    identifier: int
    content: bytes
    records: tuple[tuple[WriteTicket, int], ...]
    raw: bool

    @property
    def physical_bytes(self):
        return len(self.content)


class ExtentAllocator:
    """Not thread-safe. Upper completion requires entire extent success."""

    def __init__(self, block_count=1, packing='sequential', *,
                 max_staged_records=16, flush_deadline_ticks=10,
                 max_in_flight_extents=64, max_physical_bytes=1024 * 1024):
        if block_count not in SUPPORTED_BLOCK_COUNTS or packing not in ('sequential', 'best_fit'):
            raise ValueError('invalid extent geometry or packing policy')
        if (min(max_staged_records, flush_deadline_ticks, max_in_flight_extents, max_physical_bytes) <= 0
                or max_physical_bytes % BLOCK_BYTES):
            raise ValueError('invalid memory/device bounds')
        self.block_count, self.packing = block_count, packing
        self.max_staged_records, self.flush_deadline_ticks = max_staged_records, flush_deadline_ticks
        self.max_in_flight_extents, self.max_physical_bytes = max_in_flight_extents, max_physical_bytes
        self.staged, self.in_flight, self.committed_extents = [], {}, {}
        self.mapping_table, self.latest_generation = {}, {}
        self._ticket_identifier = self._extent_identifier = self._current_tick = 0
        self._oldest_staged_tick = None
        self.allocated_physical_bytes = self.submitted_physical_bytes = 0
        self.completed_physical_bytes = self.successful_physical_bytes = 0
        self.completed_logical_bytes = self.failed_upper_writes = 0

    @property
    def staged_payload_bytes(self):
        return sum(len(ticket.payload) for ticket in self.staged)

    def advance_tick(self, tick):
        if not isinstance(tick, int) or tick < self._current_tick:
            raise ValueError('time must be monotonic integral ticks')
        if self.staged and tick - self._oldest_staged_tick >= self.flush_deadline_ticks:
            self.flush()
        self._current_tick = tick

    def write(self, logical_page, payload, *, raw_page=None, tick=None):
        """Return an unacknowledged ticket. Admission never invents raw bytes."""
        if not isinstance(logical_page, int) or not 0 <= logical_page < 2**32:
            raise ValueError('invalid logical page')
        if not isinstance(payload, bytes) or not 0 < len(payload) <= BLOCK_BYTES:
            raise ValueError('invalid immutable payload')
        raw = len(payload) > MAX_COMPRESSED_BYTES
        if raw and len(payload) != BLOCK_BYTES:
            if not isinstance(raw_page, bytes) or len(raw_page) != BLOCK_BYTES:
                raise ValueError('raw fallback requires complete original page')
            payload = raw_page
        if tick is None:
            tick = self._current_tick
        self.advance_tick(tick)
        if len(self.staged) >= self.max_staged_records:
            self.flush()  # Backpressure instead of unbounded staging.
        self._ticket_identifier += 1
        generation = self.latest_generation.get(logical_page, 0) + 1
        self.latest_generation[logical_page] = generation
        ticket = WriteTicket(self._ticket_identifier, logical_page, generation, payload, raw)
        if not self.staged:
            self._oldest_staged_tick = tick
        self.staged.append(ticket)
        if len(self.staged) == self.max_staged_records:
            try:
                self.flush()
            except BufferError:
                pass  # Ticket stays staged, without an upper success completion.
        return ticket

    def _pack(self):
        capacity = self.block_count * BLOCK_BYTES
        groups, current = [], []
        records = (sorted(self.staged, key=lambda r: (-len(r.payload), r.identifier))
                   if self.packing == 'best_fit' else self.staged)
        for ticket in records:
            if ticket.raw:
                if current:
                    groups.append(current)
                    current = []
                groups.append([ticket])
                continue
            if self.packing == 'best_fit':
                candidates = [group for group in groups if not group[0].raw and
                              len(group) < MAX_PACKED_RECORDS and
                              HEADER.size + DESCRIPTOR.size * (len(group) + 1) +
                              sum(len(item.payload) for item in group) + len(ticket.payload) <= capacity]
                if candidates:
                    max(candidates, key=lambda group: sum(len(item.payload) for item in group) +
                        len(group) * DESCRIPTOR.size).append(ticket)
                    continue
                groups.append([ticket])
                continue
            needed = HEADER.size + DESCRIPTOR.size * (len(current) + 1) + sum(
                len(item.payload) for item in current) + len(ticket.payload)
            if current and (len(current) == MAX_PACKED_RECORDS or needed > capacity):
                groups.append(current)
                current = []
            current.append(ticket)
        if current:
            groups.append(current)
        return groups

    def flush(self):
        """Seal and submit staged records; publish no authoritative mappings."""
        if not self.staged:
            return []
        groups = self._pack()
        total_bytes = sum(BLOCK_BYTES if group[0].raw else self.block_count * BLOCK_BYTES
                          for group in groups)
        if (len(self.in_flight) + len(groups) > self.max_in_flight_extents or
                self.allocated_physical_bytes + total_bytes > self.max_physical_bytes):
            raise BufferError('bounded space or in-flight queue exhausted')
        submitted = []
        for group in groups:
            content, offsets = serialize(group, self.block_count)
            self._extent_identifier += 1
            extent = SubmittedExtent(self._extent_identifier, content,
                                     tuple(zip(group, offsets)), group[0].raw)
            submitted.append(extent)
        for extent in submitted:
            self.in_flight[extent.identifier] = extent
            for ticket, _ in extent.records:
                ticket.state = 'in_flight'
            self.allocated_physical_bytes += extent.physical_bytes
            self.submitted_physical_bytes += extent.physical_bytes
        self.staged.clear()
        self._oldest_staged_tick = None
        return submitted

    def complete(self, extent_identifier, *, success=True, completed_bytes=None):
        """Torn/failed writes never publish mappings or acknowledge upper success."""
        extent = self.in_flight[extent_identifier]
        if completed_bytes is None:
            completed_bytes = extent.physical_bytes if success else 0
        if (not isinstance(completed_bytes, int) or not 0 <= completed_bytes <= extent.physical_bytes
                or completed_bytes % BLOCK_BYTES or (success and completed_bytes != extent.physical_bytes)):
            raise ValueError('invalid aligned completion')
        del self.in_flight[extent_identifier]
        self.completed_physical_bytes += completed_bytes
        if not success:
            for ticket, _ in extent.records:
                ticket.state = 'failed'
                self.failed_upper_writes += 1
            return
        self.successful_physical_bytes += extent.physical_bytes
        self.committed_extents[extent.identifier] = extent.content
        for ticket, offset in extent.records:
            previous = self.mapping_table.get(ticket.logical_page)
            if previous is None or previous.generation < ticket.generation:
                self.mapping_table[ticket.logical_page] = RecordLocation(
                    ticket.logical_page, ticket.generation, extent.identifier,
                    offset, len(ticket.payload), extent.raw)
                ticket.state = 'committed'
            else:
                ticket.state = 'superseded'
            ticket.upper_completed = True
            self.completed_logical_bytes += BLOCK_BYTES

    def read(self, logical_page):
        mapping = self.mapping_table[logical_page]
        content = self.committed_extents.get(mapping.extent_identifier)
        if content is None:
            raise CorruptExtentError('committed extent missing')
        return read_record(content, mapping)
