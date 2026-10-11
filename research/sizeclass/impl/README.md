# Issue #33: bounded size-class extent model

This is **rootless Python research**, not a tested kernel implementation, a
persistent on-disk driver format, or a GC simulator. There are no privileged
host/device operations. Legacy reviewer snippets are retained unchanged.

## Reproduction

From the repository root:

```sh
python3 -B research/sizeclass/impl/test_allocator.py -v
python3 -B research/sizeclass/test_geometry.py -v
python3 -B research/sizeclass/legacy/test_known_defects.py -v # five intentional RED cases
```

The new tests run independently and do **not** change the deliberately failing
legacy fixtures. Work remains for Issue #34 before GC or performance conclusions.

## Wire layout: version 1 (little endian)

Aligned extent lengths: 4096, 8192, 16384, 65536 bytes. An uncompressed 4096-B
page is stored as exactly 4096 raw bytes, with the mapping marked `raw`.
Compressed extents have a 32-byte header and a frozen 32-byte descriptor table,
followed by contiguous payloads and zero padding. No record's offset is assigned
until the number of descriptors is fixed. Each descriptor has:

| Field | Bytes | Meaning |
| --- | ---: | --- |
| logical slot | 8 | unsigned 64-bit |
| generation | 8 | unsigned 64-bit, strictly increasing per slot |
| payload offset | 4 | byte offset from start of extent |
| payload length | 4 | 1..4095 bytes |
| payload CRC32 | 4 | checksum of exact payload |
| flags | 4 | zero in v1 |

Header: `magic[4] = SZSC`, `version:u16 = 1`, `header_bytes:u16 = 32`,
`extent_id:u64`, `descriptor_count:u32`, `extent_bytes:u32`,
`metadata_crc32:u32` (at byte offset 24), `flags:u32 = 0`.
Metadata CRC is taken with its own 4-byte field zero over the 32-byte header
and full descriptor table. Payload CRC is separately validated on read; other
records' payloads are not necessary for a cached-descriptor read. Metadata is
presumed resident in RAM when computing `payload_blocks`. If not cached, block
zero is also counted, unless it overlaps the requested payload read.

For 2072-byte compressed records: 1/3/7/31 records in 4/8/16/64 KiB extents.
The 64 KiB extent occupies 32 + 31*(32+2072) = **65256** bytes before padding.
This layout is a **proposal**, incompatible with the original research's
8-byte-header/8-byte-descriptor geometry and the current kernel's wire format.
Comparisons must use each actual serialized schema and identical flush cutpoints.

## Completion, failure, memory and ownership contract

- `stage(slot, generation, payload, raw_page=...)` validates and *only* retains
  volatile records. The caller must supply a real raw 4 KiB page for fallback;
  padding compressed data would corrupt readback. No logical write is completed
  at this step.
- `flush()` seals a finite set of staged extents, computes final descriptors,
  and returns submitted extent IDs; media is **not** authoritative. In-flight
  images and record objects stay pinned until their explicit completion.
- `complete(extent_id, success=True)` validates a full extent, records physical
  bytes, then publishes mapping updates only for the latest outstanding
  generation. A failed or torn extent never publishes a mapping. Older committed
  versions and sibling records remain readable. A stale completion cannot
  replace a newer generation. Logical completed bytes count only mappings
  actually published, at 4096 bytes per record.
- `max_buffered_bytes`, `max_buffered_records`, `max_staged_extents`,
  `max_inflight_extents` and logical `flush_deadline` bound resource use.
  Backpressure is explicit; the caller must complete work or fail its upper IO,
  not spin or silently assume future arrivals. An invalid completion does not
  dequeue the outstanding IO. Staged superseded bytes are freed, while submitted
  superseded bytes remain pinned until completion.
- All state transitions are **single-threaded** in this model. A kernel port
  requires synchronization, BIO ownership references, lifetime barriers and
  completion ordering. This module does not establish production-safe BIO
  semantics or durability after reboot; stale volatile maps after power loss
  are out of scope.
- Each newly written extent has an immutable, unique ID and an independent
  media byte array. Actual lower-block assignment, capacity/reserve and GC are
  **not** modeled here; Issue #34 must implement and verify those separately.
  `partial_physical_bytes` is failed-write prefix traffic and is not counted as
  successfully committed bytes. `submitted_physical_bytes` counts attempted
  whole-extent writes regardless of their completion outcome.
- `read` checks the selected record's exact CRC and returns physical 4 KiB
  block counts based on that record's serialized byte range. A corrupt record
  or mapping fails closed. This is a synthetic model: no real block reads or
  kernel decompression are performed.

`pack_windows()` models a strictly source-ordered one-current-bin policy vs
bounded reorder over records already admitted before the *same* forced flush.
It is an illustrative packing control, **not** proof of production swapz
scheduling equivalence or of a best achievable offline packing bound.

## Remaining work before acceptance

This PR resolves the allocator-state/serialization prototype and unit tests,
**not Issue #34**. No finite physical space, 1 MiB GC segments, relocation,
interruptible GC, raw BIO completion ownership, hardware timestamps, fio traces,
or write-amplification claims are implemented. Do not merge it into PR #31 or
interpret passing tests as hardware evidence.
