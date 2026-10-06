# swapz V1 design notes

## Primary objectives

1. Improve swap throughput on roughly 10-100 MB/s serialized storage.
2. Reduce host bytes written when pages are LZ4-compressible.
3. Avoid repeatedly rewriting the same LBA range on flash-backed swap media.
4. Remain correct on devices with no DISCARD support.
5. Keep the kernel implementation small enough to reason about under memory pressure.

## Non-goals

Persistent metadata, crash recovery, deduplication, encryption, filesystem-backed swap, hibernation, multi-queue NVMe performance, and capacity overcommit.

## Mapping

One 8-byte mapping entry per logical 4 KiB page:

```text
u32 physical_block
u16 stored_length
u8  record_index
u8  flags
```

Memory cost is 2 MiB per GiB of logical swap.  This is intentionally simple and allocation-free during I/O.

## Packed container

A compressed lower block contains a fixed header and up to eight records.  Each record identifies its logical page, offset, and LZ4 payload length.  The header is not persistent metadata in the recovery sense; it is only used to validate/read the block during the current boot.

Incompressible pages use one raw 4 KiB lower block and are identified by the RAM mapping flag.

## Write atomicity

A logical mapping is changed only after the new lower 4 KiB block completes successfully.  Until then the previous mapping remains readable.  Packed write BIOs are completed only after their shared container reaches the backing device.

A lower read/write failure marks the target failed.  DISCARD failures are explicitly excluded from this rule and only disable the optional lower-discard optimization.

## Arenas

The device is split into equally sized arenas.  Minimum arena size is:

```text
logical_pages + max(logical_pages / 4, 256 blocks)
```

At least two arenas are required.  If the physical device is much larger, additional arenas are created so rotations traverse most of the backing device.

Invariant after a successful rotation:

> Every valid logical mapping points into the current arena.

Normal rewrites append new versions to that same arena.  On rotation, all currently valid mappings are re-read and appended into the next arena.  The old arena then contains no live mappings.

This is deliberately less efficient than segment GC but dramatically easier to validate.  V2 should replace it only if benchmarks show the core compression/packing/endurance premise succeeds.

## Feature fallback policy

### Upper DISCARD

The mapper advertises discard independent of the backing device.  Logical discard clears the RAM mapping.  If userspace/kernel swap activation cannot request page discards, the target still works; freed pages may be copied during compaction until they are overwritten.

### Lower DISCARD

At target creation:

```text
max_discard_sectors != 0 && discard_granularity != 0
```

allows lower discard.  Before an old arena is reused, only its previous high-water range is discarded.  Any runtime discard error permanently disables lower discard for that target and normal overwrite continues.

### Compression

If LZ4 cannot save at least 512 bytes, store the page raw.  There is no dependency on a minimum compression ratio for correctness.

## Memory-pressure behavior

- mapping and arena arrays are allocated at target creation;
- four 4 KiB working buffers and LZ4 workspace are preallocated;
- target I/O is processed on a `WQ_MEM_RECLAIM` workqueue with `max_active=1`;
- lower I/O uses a private `dm_io_client`;
- no per-request heap allocation is performed by `swapz` itself; Device Mapper provides per-BIO target storage;
- lower discard uses `GFP_NOIO`.

## Why arena rotation instead of V1 segment GC

Segment GC needs reverse mappings or self-describing metadata for raw blocks, victim selection, free-segment accounting, and more failure paths.  Arena rotation costs compaction bandwidth but gives a much smaller correctness surface and naturally sweeps writes over the backing partition.  It is appropriate for proving whether the basic I/O/endurance idea is worth a V2 allocator.