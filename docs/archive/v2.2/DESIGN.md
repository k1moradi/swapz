# swapz V2.2 design notes

## Why V2 exists and why V2.1 follows it

V1 proved the core block path can be correct on Linux 7.0.x: LZ4 packing, raw fallback,
logical discard, flush handling, fault propagation, repeated target lifecycle, randomized
rewrites, and real swap pressure all passed validation.

Its allocator did not meet the performance/endurance goal.  V1 copied the complete live
logical set into the next arena whenever the current arena filled.  The validation run
showed that partially-compressible and incompressible churn could write about 2.86x the
raw baseline and that a rotation-triggering write could stall for about one second on the
1 ms delayed test device.

V2 keeps the proven I/O/mapping path but replaces whole-live-set arena rotation with
segment-local garbage collection.

## Primary objectives

1. Improve swap throughput on roughly 10-100 MB/s serialized storage.
2. Reduce actual lower-device host bytes written when pages are LZ4-compressible.
3. Avoid catastrophic write amplification on partially-compressible or raw workloads.
4. Keep writes append-only inside small segments and rotate allocation across the device.
5. Remain correct on devices with no DISCARD support.
6. Keep the reclaim path allocation-free and simple enough to reason about.

## Non-goals

Persistent metadata, crash recovery, deduplication, encryption, filesystem-backed swap,
hibernation, multi-queue NVMe tuning, and capacity overcommit.



## V2.1 serialized physical-write batching

Validated V2 fixed whole-live-set compaction but still issued each physical 4 KiB output as
one synchronous lower request.  On a 1 ms/request test stack that request granularity was
the dominant QD8 bottleneck.

V2.1 keeps lower queue depth equal to one and adds a preallocated 32 KiB physical output
batch:

```text
logical writes
    |
LZ4 pack / raw fallback
    |
4 KiB physical output blocks
    |
up to 8 consecutive blocks
    |
one synchronous lower write (up to 32 KiB)
```

This is request coalescing, not parallel lower I/O.

A staged physical block carries the logical mapping records that should become authoritative
only after the lower batch succeeds.  On success, mappings are installed in staged order
and the upper BIOs are completed.  On lower write failure, every upper BIO in the batch
fails and none of the batch mappings are published.

The batch is forcibly committed before:

- advancing to another segment;
- a logical read;
- upper DISCARD;
- FLUSH or PREFLUSH;
- declaring a GC victim fully relocated and reusable.

GC uses the same batching path.  Foreground and GC data are copied into the dedicated
preallocated batch buffer before their source scratch buffers can be reused.

The batch buffer is allocated when the target is created.  V2.1 does not add runtime heap
allocation to the reclaim path.

The single-record pack-coalescing delay is shortened from 500-1000 us to 50-100 us.  The
intent is to reduce V2's QD1 latency penalty while still allowing nearby concurrent swap-out
requests to form compressed containers.

New status counters are:

```text
physical_write_reqs
multi_write_reqs
max_write_batch
```

Validation must compare these with actual lower block-device write-I/O counts.

## V2.2 streaming experiment

V2.1 proved that larger serialized lower requests remove much of the 4 KiB command overhead,
but it still prepared and submitted physical output synchronously. V2.2 separates upper
swap processing from lower drain with exactly two bounded preallocated stream buffers.

Three policies are selectable per target:

```text
immediate
    stage one physical block and synchronously drain it
    control/baseline

opportunistic
    one asynchronous lower write may be in flight
    fill the other buffer while it writes
    do not intentionally sleep to make a batch larger

staged
    same double-buffer pipeline
    compressed foreground writes may complete after their authoritative
    compressed representation is copied into a stream buffer
```

At most one lower write is in flight. The goal is not lower queue-depth parallelism; it is
to overlap CPU compression/packing with media latency while keeping append order simple.

The target accepts a configurable physical batch ceiling from 4 KiB through 1 MiB. The
ceiling is an experiment parameter, not a hard-coded sweet spot. The benchmark sweeps
upward until physical drain throughput reaches a plateau and then uses concurrent swap-in
p99 latency to choose the smallest acceptable plateau point.

### Staged authority and recall

A staged foreground record is identified by:

```text
logical page
generation
buffer id
block index
record index
```

Generation changes on overwrite or logical DISCARD. Completion of an older asynchronous
write therefore cannot publish stale data.

A logical READ first checks the staged reference. If the current generation still resides
in either the FILL or INFLIGHT buffer, swapz decompresses/copies it directly from RAM and
does not wait for the lower device.

A READ does **not** itself make the swap slot dead. The buffered record remains valid until
the upper layer later sends DISCARD or overwrites the slot. Only then may an unsent record
be removed during fill-buffer compaction. This avoids assuming Linux frees a swap slot at
read completion.

Before an unsent buffer is submitted, stale generations are removed and the remaining
compressed records are repacked across 4 KiB containers. This can avoid lower writes for
records invalidated before submission. An already-submitted lower write cannot be surgically
retracted; if its record became stale, completion simply declines to publish that obsolete
generation.

### Early completion safety

Early upper completion is currently restricted to compressed, non-GC foreground records in
`staged` mode. Raw 4 KiB pages are not early-completed because retaining a full-size copy
would not materially release RAM.

If an asynchronous lower write fails after an early completion, the target enters a failed
write state but retains the affected stream buffer so staged reads/swapoff can still recover
the authoritative compressed data. New writes are rejected; staged/on-disk reads and
logical invalidation remain available.

### Ordering barriers

The stream is drained before operations that require persistent ordering or allocator
state to be fully published, including:

- FLUSH/PREFLUSH;
- segment transition and victim GC;
- suspend/teardown;
- other places where physical mapping publication is required.

Normal staged reads intentionally do not drain the stream.

### Memory bound

Both stream buffers and their metadata are preallocated at target creation. No reclaim-path
heap allocation is needed. The maximum buffer size is bounded by the configured batch
ceiling and by the 1 MiB segment size.


## Logical mapping

The logical map remains one 8-byte entry per logical 4 KiB page:

```text
u32 physical_block
u16 stored_length
u8  record_index
u8  flags
```

This costs 2 MiB per GiB of logical swap.

V2 adds one byte of live-record accounting per physical 4 KiB block and small per-segment
arrays.  A 1 GiB physical backing device therefore needs about 256 KiB for the per-block
reverse accounting, plus the logical map.

The per-block counter is enough to know exactly when a physical block no longer contains
any live logical mappings.  It avoids a much larger full reverse-map structure.

## Physical segments

The usable backing device is divided into fixed 1 MiB segments:

```text
256 x 4 KiB blocks
```

Segment states are:

```text
FREE
OPEN
CLOSED
CLEANING
```

There is exactly one OPEN append segment.  New containers and raw pages are appended
sequentially to it.

FREE segments are selected using a rotating allocation cursor so unused/free host LBA
regions are traversed broadly instead of always choosing the lowest address.

## Capacity reserve

Compression is never required for capacity.

V2 requires physical backing of at least:

```text
logical_pages + max(logical_pages / 4, two segments)
```

So the device has at least 25% GC reserve and never depends on a promised compression
ratio.

`swapzctl` may remain more conservative than this minimum; large physical/logical ratios
are useful on SD/USB media because they provide more append space between reuses.

## Packed container

Compressed pages still use the V1 4 KiB container format with up to eight logical records.
Each record contains its logical page, payload offset, and compressed length.

Poorly-compressible pages fall back to a raw 4 KiB block.

No on-disk metadata is needed for recovery.  All state is intentionally volatile and the
target starts empty each boot.

## Mapping accounting

When a mapping is installed:

1. its previous physical record is unaccounted;
2. the new physical block's live-record counter is incremented;
3. if that block transitions from zero to one live record, the segment live-block count is
   incremented;
4. the logical mapping is published only after the lower write succeeded.

Overwrite and logical DISCARD perform the inverse accounting.

Thus each CLOSED segment has an exact count of physical blocks that still contain at least
one live mapping.

## Segment garbage collection

Normal writes consume FREE segments sequentially.

One FREE segment is kept as a reserve.  When allocation opens the last FREE segment, V2
selects a CLOSED victim with the smallest live-block count and copies only logical mappings
that still point into that victim.

The cleaner:

1. marks the victim CLEANING;
2. scans the compact logical map once;
3. builds a bounded reverse scratch index for only that 1 MiB victim;
4. groups live logical mappings by their source physical block;
5. reads each live source block once;
6. repacks only that source block's still-live records;
7. installs new mappings only after successful lower writes;
8. verifies the victim has zero live physical blocks;
9. optionally discards the old high-water range;
10. marks the victim FREE.

The reverse scratch is fixed-size: 256 blocks x 8 logical-page IDs plus one byte of count
per block, about 8.25 KiB per target.  It is not a persistent or global reverse map.

Preserving source-container grouping is important: a live source container is relocated as
one unit, so GC should not expand one live source physical block into an arbitrary number of
destination blocks.  It also prevents rereading the same packed source block once per
logical record.

The logical-map scan is deliberate.  It avoids doubling every logical mapping with
intrusive reverse-list pointers.  On the intended slow-media target, the design hypothesis
is that scanning RAM is cheaper than unnecessary flash/HDD traffic.  V2 benchmarking must
prove this assumption.

## Victim policy

V2 initially chooses the CLOSED segment with the fewest live physical blocks.

A candidate must leave GC headroom in the destination segment.  This is intentionally much
simpler than F2FS cost-benefit cleaning or hot/cold logs.

If benchmarks later show repeated hot-segment reuse or poor host-LBA distribution, hot/cold
classification is a possible V2.x optimization rather than a reason to reintroduce V1
whole-live-set copying.

## Write atomicity

The logical mapping is changed only after the replacement lower block succeeds.

A failed foreground write therefore leaves the previous known-good mapping intact.  GC uses
the same rule.

A lower read/write failure marks the target failed.  Lower DISCARD failure does not: it
only disables physical discard for that target.

## Buffer ownership

Foreground writes have dedicated preallocated input/compression pages.

GC uses separate input/compression scratch pages.

This separation is required because a foreground store can trigger segment advance and GC;
the cleaner must never overwrite the foreground payload that caused the transition.

## DISCARD fallback

### Upper DISCARD

The mapper advertises logical discard independently of the lower device.  Logical discard
invalidates the mapping and updates segment live-block accounting.

If swap page discard is unavailable, correctness is unchanged.  GC simply treats more old
mappings conservatively until they are overwritten.

### Lower DISCARD

Lower discard is enabled only if the actual backing queue reports nonzero discard capability.
It is issued only for a fully cleaned segment's prior high-water range.

The first runtime discard failure disables lower discard permanently for that target.
Ordinary reads/writes and segment reuse continue.

## Memory-pressure behavior

All state needed for normal I/O and GC is allocated at target creation:

- logical mapping array;
- one-byte per-physical-block live-record array;
- segment state/live/high-water/cycle arrays;
- foreground input/compression pages;
- GC input/compression pages;
- I/O and pack pages;
- LZ4 workspace;
- private `dm_io_client`;
- serialized `WQ_MEM_RECLAIM` workqueue.

No swap I/O requires a `swapz` heap allocation.

## Required V2 measurements

V2 is successful only if testing shows:

- V1 correctness coverage remains green;
- partially-compressible and incompressible churn no longer produces V1-style multi-x write
  amplification;
- GC copies only the chosen victim's live data;
- GC latency is substantially below V1 full-live-set rotation latency;
- compressible workloads still reduce actual lower-device sectors written;
- host-LBA allocation traverses the available segments broadly;
- QD1 and realistic Linux swap workloads remain acceptable on slow devices.

If the logical-map scan itself becomes a measurable bottleneck, the next optimization is a
bounded reverse index, not whole-live-set arena copying.
