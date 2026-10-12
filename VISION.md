# swapz vision — optimize **real physical I/O**, not a compression score

> **Our ultimate success criterion is fewer actual physical 4 KiB-equivalent
> I/O transfers on the SD card, SSD or HDD under a verified workload, while
> preserving correct swap behavior and acceptable swap-in latency. Passing
> more tests or achieving a better simulated compression ratio is not, by
> itself, a performance win.**

This is the project's **north star and acceptance standard** for V3 and all
later versions. [V3_GOALS.md](V3_GOALS.md) is the implementation roadmap;
this document defines *what we are optimizing* and *what evidence counts*.

## 1. Start with the device, not the compressor

Linux swap presents 4 KiB logical pages on this project's supported
`PAGE_SIZE=4096` kernels. If a page's LZ4 payload is 900 bytes, that does
**not** automatically mean a device can read or write only 900 bytes.
Block-layer I/O has address and alignment granularity, and device-specific
request, transfer and media-program costs. An isolated compressed object may
still consume a full 4 KiB addressed block.

**Our chosen allocation and accounting unit is an aligned 4 KiB lower block.**
This is a design decision, not a claim that every SSD's NAND page, every HDD's
physical sector, or every device's internally transferred unit is precisely
4 KiB. Some drives expose 512-byte logical sectors or have larger internal
write/erase granularity. Kernel and device counters measure *host-visible*
sectors/requests; only hardware telemetry can substantiate internal flash
programming or endurance claims.

The key question is therefore: **For the same useful swap workload, how many
4 KiB-equivalent blocks and lower I/O requests were actually transferred?**

A 16 KiB lower request counts as **four 4 KiB-equivalent blocks** and **one
request**. We report both numbers; collapsing requests and bytes into a
single “I/O count” would conceal important tradeoffs.

## 2. Packing density is useful only if it removes actual I/O

Our zsmalloc-inspired approach is *size-class-aware grouping and compaction*
of LZ4-compressed objects, adapted to block storage:

1. Compress incoming 4 KiB logical pages to discover their **actual** sizes,
   including real format/header/descriptor costs.
2. Reorder **only independent pages already admitted to a bounded window**,
   preserving same-slot generations and all read, flush/FUA and discard
   ordering barriers.
3. Fit complementary sizes into as few aligned 4 KiB backing blocks as
   possible. If two payloads are 2,200 B and 1,600 B, a V3 two-record
   header+descriptor overhead of 48 B yields **3,848 B**: one 4 KiB block
   rather than two. The extra space is useful only when it changes lower
   transfer size/count, not merely an in-memory packing statistic.
4. Where 4 KiB containers cannot pack efficiently, permit aligned 8/16 KiB
   physical extents with individually addressable compressed objects.
   For example, two 2,072 B objects plus the older 24 B 4 KiB container
   overhead require **4,168 B** and therefore cannot share a 4 KiB block
   regardless of reorder policy. A 16 KiB extent can pack seven such objects
   across four 4 KiB backing blocks, rather than seven standalone blocks.
5. During overwrites and discards, treat stale records as reclaimable but
   relocate **only still-live objects**. Repack survivors by size and recycle
   victims only after completed lower I/O, generation-authoritative mapping
   updates and liveness/read-ownership verification.

**Avoid claiming “better compression” when only container arrangement
changed.** We may store the same exact LZ4 bytes more densely; that is
*physical layout efficiency*, distinct from LZ4's compression ratio.

## 3. A write win can be a read loss

Packing multiple objects into one 4 KiB block often helps both capacity
and I/O. But an object crossing a physical 4 KiB boundary can make a
**single swap-in** require extra lower reads: a metadata block, and one or
two payload blocks. Cache hits may change actual transfer counts.

Thus **“minimize writes at any cost” is not the vision**. The real objective
is a device- and workload-specific frontier between:

- completed lower **write 4 KiB-equivalent blocks and write requests**;
- completed lower **read 4 KiB-equivalent blocks and read requests**;
- **GC and relocation I/O**, including reads and rewrite traffic, never
  hidden from totals;
- achieved swap-in/swap-out rate, congestion, real drain and **p95/p99
  swap-in latency**;
- compression, decompression, reordering and GC **CPU time**, worker stalls,
  memory buffers and reserve pressure;
- integrity, exact completion authority, flush/FUA ordering, liveness
  correctness and safe teardown.

Keep the budget adjustable: a device with very expensive random reads may
prefer a 1- or 2-block read limit even when this writes more blocks. A
write-constrained SD card may justify a different tradeoff than an HDD.
Policies are **hypotheses** until both reads and writes are measured.

## 4. Precisely define the primary measurements

For every completed, fully drained *paired benchmark*, report the following
**separately for reads and writes**, rather than a single opaque “ratio”:

| Measure | Grounded definition |
| --- | --- |
| Logical useful bytes | Accepted/read-back-verified 4 KiB logical pages; distinguish offered, submitted and actually completed operations |
| Lower write sectors | Host-visible sectors transferred by the specifically owned backing device during the measured phase (state sector size) |
| Lower write 4 KiB equivalents | Lower write bytes / 4096, only when supported by sector deltas and alignment; a 16 KiB request is four units |
| Lower write requests | Measured completed lower write commands/BIOs; separately report flushes, discards and any aggregation |
| Lower read sectors / 4 KiB equivalents / requests | The corresponding physical lower read measurements, especially under cold swap-in and GC |
| GC read and write bytes / requests | Lower I/O caused by live relocation, included in total traffic and **also** displayed separately |
| Useful logical / lower write bytes | Explicitly labeled **write-byte reduction** for a comparable workload, not compression ratio or I/O-operation reduction |
| Read amplification | Lower backing read blocks or bytes per successfully serviced logical swap-in; distinguish cache effects and GC |
| Upper completion latency and drain | p50/p95/p99 swap-in, actual achieved IOPS, pending I/O and flush/drain at end, not merely requested rate |
| Resource cost | CPU, memory staging, allocator reserve, GC occupancy and failures |

Counters from driver status must **reconcile** with independent backing
device sector/request deltas where possible. Explain unavoidable differences
from filesystem/device caching, merged requests, other writers, counter
semantics or writes outside the measurement interval. Isolate the backing
device; otherwise don't label aggregate deltas as swapz traffic.

The current V3 engine's memory-backed and sanitizer tests are valuable
correctness/geometry evidence, but are **not** lower-device measurements.
For instance, the modeled 16 x 2,072 B example (65,536 B old layout versus
40,960 B V3) is an encouraging hypothesis, **not an SD-card benchmark**.

## 5. What makes a comparison trustworthy

A qualified V2.2-versus-V3 benchmark must have:

- **The exact same logical workload:** input pages, actual LZ4 compressed
  payload-size histogram, random seeds, logical capacity, read/write mix,
  hot/cold churn and verification rules.
- **The same physical environment:** identical owned SD/SSD/HDD device or
  controlled device setup, service-rate/latency assumptions, sector alignment,
  queue-depth constraints and cache/flush mode.
- **Comparable achieved load:** *actual* reader and writer IOPS, throughput
  and latency; a requested 500 IOPS that achieved 140 is **not** equivalent
  to one that achieved 500. Include low-QD and competing readers.
- **Long enough to include lifecycle costs:** steady-state overwrite,
  segment wrap, live-object GC, read amplification, reserve pressure,
  failures and teardown. Startup/one-window geometry alone is not enough.
- **No invisible work:** wait for writes, GC, lower callbacks and relevant
  flushes to drain; don't call RAM staging an on-device write saving or
  declare upper completion equal to durable lower completion.
- **Integrity and provenance:** independent byte-for-byte/CRC32C readback,
  reproducible artifacts, source blob IDs, exact `.ko` hash/vermagic,
  active module and mapper identity, owned backing-device identity, kernel
  version, lower counters and full command exit codes.
- **Repeatability:** warm-up, multiple runs, counterbalanced order, per-run
  and aggregate results including median, p95/p99 and confidence limits
  where sample sizes support them. Don't turn a tiny p99 sample into a
  reliable tail-latency claim.

A memory-backed `null_blk` device is the essential **first loaded-kernel
integrity and controlled-I/O gate**, but it is not a substitute for physical
SD-card, SSD or HDD validation. The current V3 alpha is explicitly
**null_blk-only** until its GC and lifecycle safety gates pass. Never
circumvent that guard to obtain physical-media results. **Never reboot.**

## 6. Release decision: what counts as success or failure

**Correctness is non-negotiable**, and passing tests is the *entry ticket*,
not the success metric.

A performance claim of “V3 is better” requires all of:

1. Exact logical data integrity, correct completion semantics, safe drain,
   GC/reclamation and device-ownership behavior under the target workload.
2. A **material, repeated reduction in measured completed lower 4 KiB
   equivalent I/O**, reported for **both writes and reads** plus actual
   lower requests, including GC overhead.
3. A demonstrated device-relevant benefit—less contention, higher useful
   completed throughput, better or acceptable swap-in p99, or fewer measured
   host writes on endurance-constrained media—**without** an unacceptable
   CPU/RAM, read-amplification or tail-latency regression.
4. Results from the **actual loaded kernel target** on the owned physical
   target-media class, not solely a geometry calculator, memory test or
   compile-success badge.

A configuration that reduces writes but doubles cold swap-in traffic and
causes harmful latency regressions may be **worse**, even if its compression
ratio looks outstanding. A faster benchmark with unmatched achieved reader
load is **inconclusive**. A simulated write win with no real lower-sector
reduction is **not a win**.

No universal “X% fewer I/Os” or guaranteed flash-endurance number is
assumed in advance. Define the baseline and acceptable latency/CPU guardrails
**before** seeing experimental results. Preserve the best Pareto-efficient
policy for each verified device class, and retain V2.2 as the control until
V3 conclusively earns replacement.

## 7. What this means for development priorities

Features should be prioritized by their capacity to improve the measured
host-visible I/O frontier: bounded size reordering, 4 KiB-first grouping,
8/16 KiB crossing when it removes net blocks, targeted reads, live-only
size-class GC, failure-safe real DM completion, counters and a rigorous
physical-media harness. Additional micro-optimizations, synthetic-ratio
records and green CI checks are welcome **only insofar as they establish
correctness or advance that measurable outcome**.

This standard applies to main-developer implementation decisions, Codex's
independent tests, PR reviews, release notes and the final V3 go/no-go gate.
