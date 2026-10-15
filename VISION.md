# swapz vision — optimize **real device I/O cost**, not compression scores

> **Our ultimate success criterion is less *measured, host-visible lower-device
> I/O* under an identical, verified swap workload on the actual SD card, SSD
> or HDD: record both read/write BYTES and request COUNTS, including GC, while
> preserving correct data, achieved useful throughput, latency and CPU cost.
> 4 KiB is our present V3 *allocation and normalization size*, NOT a
> universal physical-device I/O operation or sector size. Passing more tests
> or achieving a higher simulated compression ratio is not a performance win.**

**Current engineering policies:** [README.md](README.md),
[coding_standards.md](docs/coding_standards.md),
[testing_standards.md](docs/testing_standards.md), [compile.md](docs/compile.md),
and [benchmark.md](docs/benchmark.md) are the mandatory six documents read
at the start of **every agent task**. New lessons and policies belong in
the four standards; README communicates user-facing changes, while this
VISION governs success criteria. Only `main` is used and all builds
reuse `~/swapz/build/`. Historical reports are evidence, not policy.

This is the project's **north star and acceptance standard** for V3 and all
later versions. Read [device geometry and benchmark standards](docs/benchmark.md) for 512n, 512e,
4Kn, filesystem cluster sizes, swap partitions/files and precise block-layer
stat units. [V3_GOALS.md](docs/ROADMAP.md) is the algorithm roadmap; this
document defines *what we are optimizing* and *what evidence counts*.

## 1. Start with the device, not the compressor

Linux swap presents 4 KiB logical pages on this project's supported
`PAGE_SIZE=4096` kernels. If a page's LZ4 payload is 900 bytes, that does
**not** automatically mean a device can read or write only 900 bytes.
Block-layer I/O has address and alignment granularity, and device-specific
request, transfer and media-program costs. An isolated compressed object may
still consume a full 4 KiB addressed block.

**Current V3 fixed format:** aligned 4096-byte lower allocation units, with
4/8/16KiB physical *extents*. This is a format policy for kernels where
`PAGE_SIZE=4096`, NOT a universal device read/write granularity. A 512n
disk can address 512-byte sectors, a 512e disk has 512-byte logical but
commonly 4KiB physical sectors, and a 4Kn disk has 4KiB logical sectors.
Filesystem allocation clusters are a different concept. The device may
prefer transfers larger than its logical or physical sectors.

The key question: **How many host-visible lower READ and WRITE BYTES and
REQUESTS were actually transferred for the same useful completed swap work,
including GC?** Use 4KiB *equivalents* only as normalization. A 16KiB write
means 16KiB transferred (four normalized 4KiB units) in perhaps **one
command**, NOT four physical operations. Host statistics cannot by
themselves reveal SSD NAND programming, SD-card erases or internal RMW.
Measure request counts, sectors and latency separately.

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
   header+descriptor overhead of 48 B yields **3,848 B**: one aligned 4 KiB V3 container unit
   rather than two. The extra space is useful only when it changes lower
   transfer size/count, not merely an in-memory packing statistic.
4. Where 4 KiB containers cannot pack efficiently, permit aligned 8/16 KiB
   V3 extents with individually addressable compressed objects.
   For example, two 2,072B objects with V3's 16B header and two 16B
   descriptors require **4,192B**, so they cannot share a 4KiB V3 unit
   regardless of reorder policy. A 16KiB V3 extent can pack seven such
   objects into four aligned 4KiB allocation units instead of seven.
   The older V2.x 24B header/descriptor model was also over-full at
   4,168B; these figures refer to *format layout*, not device sectors.
5. During overwrites and discards, treat stale records as reclaimable but
   relocate **only still-live objects**. Repack survivors by size and recycle
   victims only after completed lower I/O, generation-authoritative mapping
   updates and liveness/read-ownership verification.

**Avoid claiming “better compression” when only container arrangement
changed.** We may store the same exact LZ4 bytes more densely; that is
*physical layout efficiency*, distinct from LZ4's compression ratio.

## 3. A write win can be a read loss

Packing multiple objects into one aligned V3 4KiB unit can help both
capacity and I/O. But an object crossing that *V3 container* boundary can
make a **single swap-in** require extra 4KiB reads through the current
driver: a metadata unit and one or two payload units. This is NOT the
backing disk's physical sector size; cache and request scheduling may
change actual observed transfers.

Thus **“minimize writes at any cost” is not the vision**. The real objective
is a device- and workload-specific frontier between:

- completed lower **write bytes/512-byte stat sectors and write requests** (4KiB equivalents only as normalization);
- completed lower **read bytes/512-byte stat sectors and read requests** (with real device geometry);
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
| Lower write sectors | **512-byte accounting sectors** from owned lower device sysfs-stat deltas, NOT the device's logical or physical sector size |
| Lower write 4 KiB equivalents | **delta write stat sectors / 8**, an accounting normalization, NOT a physical-operation count |
| Lower write requests | Measured completed lower write commands/BIOs; separately report flushes, discards and any aggregation |
| Lower read sectors / 4 KiB equivalents / requests | Same **512-byte stat units**, bytes, optional 4KiB equivalents and independently counted read requests |
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

## 5. What makes an uncompressed-baseline versus V3 comparison trustworthy

A qualified V3 performance comparison must use **bare, owned RAM-backed null_blk** (no compression) versus **V3 on an equivalent owned RAM-backed null_blk**, with:

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
2. A **material, repeated improvement in measured host-visible lower-I/O
   cost**: read/write bytes AND requests separately, with GC, accounting
   for a real device's sector geometry and not masking read regressions.
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
policy for each verified device class. The active control is uncompressed,
byte-identical logical I/O to a safely owned RAM-backed null_blk; V2.2
is retired and does not enter new benchmark gates. Physical-media
validation stays separately owner-authorized and out of scope for the
current null_blk-only V3 source.

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
