> **Supplemental/historical evidence — not current engineering policy.**
> A dated performance diagnosis; maintain current measurement rules in benchmark.md.
> The authoritative standards are [coding_standards.md](../../coding_standards.md),
> [testing_standards.md](../../testing_standards.md),
> [compile.md](../../compile.md), and
> [benchmark.md](../../benchmark.md), alongside README.md and VISION.md.
> Do not use dated branch/reset/active-swap instructions as new permission.

# V3 performance diagnosis: algorithm, implementation and evidence are different

**Finding:** The zsmalloc-inspired idea has **NOT** been disproved.
Production performance readiness has **NOT** been established. Treat the
distinction as a release-blocking engineering finding, not a failure of the
compression algorithm by itself.

Evidence: [Codex's alpha.1 loaded null_blk validation](https://github.com/k1moradi/swapz/blob/codex/pr45-live-nullblk-validation/docs/validation/v3-alpha1-2026-10-12/validation-report.md)
and the actual V3 kernel source in [PR #45](https://github.com/k1moradi/swapz/pull/45)
plus main-developer fixes in [PR #47](https://github.com/k1moradi/swapz/pull/47).
Only the exact tested alpha.1 build has *loaded-kernel* evidence; the newer
alpha.2 changes have rootless/kernel-build evidence, not loaded-host results.

## Newer loaded alpha.5 evidence (supersedes the old missing-baseline claim)

The historical alpha.1/alpha.2 assessment below remains a record of
what those revisions established, but later [Codex PR #53](https://github.com/k1moradi/swapz/pull/53)
**DID obtain a real loaded V2.2 control**, not just modeled
ordered4 geometry. On the same 1024-write, 4MiB useful logical
input and readback, V2.2 wrote **1,679,360B in 26 requests**,
while V3 alpha.5 default wrote **1,716,224B in 419
synchronous dm_io extent submissions / 420 actual backing requests**.
That is **2.20% MORE write bytes** and roughly **16x MORE write
requests** in the tested burst. Reads matched at 4MiB/1024 requests.
Both successfully read back all 1024 pages; there was no
sustained matched-achieved-IOPS curve or physical SD result.

This is a **MEASURED performance failure for the tested default
V3 workload**, not merely missing evidence or a size-binning typo.
The direct code cause is V3 calling one synchronous lower dm_io
per separate 4/8/16KiB extent, versus V2.2's larger stream
writes. Higher request setup/dispatch overhead can dominate a
similar or modestly smaller total written byte count. Smaller
16-page V3 microbursts saw beneficial write-byte reductions in
favorable coalescing scenarios, but incurred extra reads and
multi-ms write p95. No result justifies a general SD win.

[Main-developer alpha.6 PR #54](https://github.com/k1moradi/swapz/pull/54)
changes the real output pipeline, not just the planner: stage
multiple individually valid small SWZ3 extents WITHOUT publishing
authority, issue one bounded 256KiB synchronous contiguous lower
write, and then publish each only after fully confirmed lower I/O.
`lower_bulk=0` preserves the same-binary old control;
`lower_bulk=1` (DEFAULT) aggregates only *adjacent physical*
extents, adding **no padding write bytes**;
`lower_bulk=2` explicitly permits zero-filled alignment gaps
to trade more write bytes for fewer requests. Lower block-layer
requests may still split after dm_io; compare independently
measured null_blk requests, not source-level submissions.
**A performance improvement is a hypothesis until the exact
alpha.6 module is loaded under a matched V2.2 comparison.**

Later alpha.4 loaded GC tests established reserve-role rotations;
alpha.5 verified FUA/PREFLUSH and synthetic error propagation.
In a controlled GC counterexample, live-byte-only selection
doubled actual relocation traffic; alpha.5's I/O-aware policy
matched the live-count selector but did not prove a general win.
The remaining hard blockers are sustained actual request/byte
economics, read amplification/p99, further GC failures, and
separately authorized physical media.

## Evidence for the core algorithm

**Packing and size-aware reordering worked, in bounded windows.** Codex
observed these actual loaded V3 lower writes on owned memory-backed
`null_blk` for exact, independently read-back-verified pages:

| 16-page workload | Actual LZ4 output | Loaded V3 4KiB-equivalent write bytes | Interpretation |
| --- | --- | --- | --- |
| Clustered 8 large + 8 small | 8 × 2224B + 8 × 1623B | 8 × 4096B | Reordering produced complementary pairs in real 4KiB V3 containers |
| Alternating same populations | Same | 8 × 4096B | Already well arranged; reordering adds little |
| Uniform about 50% | 16 × 2082B | 10 × 4096B | 8/16KiB extents overcome the 4KiB two-record compression cliff |
| Uniform about 75% | 16 × 1055B | 5 × 4096B | Dense packing works for small records |

Total: **64 logical 4KiB pages => 31 host-visible 4KiB-equivalent
writes in 24 lower requests**. The old ordered4 `41 units` number is
**modeled geometry**, not a measured loaded V2.2 result. Do not advertise
31/41 as a proven physical-disk V2.2 speed or endurance win.

Read cost is real: across 3200 logical reads under the respective policies,
the loaded `null_blk` read-cap 0 path transferred **4100 4KiB equivalents
(1.2813x read bytes)** and cap 1 transferred **3200 (1.0000x)**. Cap 1
also increased write units from 31 to 38. This is a Pareto tradeoff, not
an unqualified “compression improvement.”

## Why the sustained workload did not show write savings

**1. Main architecture/performance limitation — insufficient grouping.**
The packed-object algorithm sees only pages that are simultaneously present
in an admitted, bounded worker window. The implementation uses a serialized
worker, synchronous lower `dm_io`, ordering barriers and flushes leftover
batches before yielding. Under low queue depth, hot/cold overwrite,
duplicate-slot, raw-page and GC workloads, many windows contain **one**
compressed record. No size-class heuristic can pair records that were
already written in different closed windows. This is **algorithmic
opportunity limited by queueing/buffering policy** (an architectural
integration problem), NOT a miscalculated CRC or broken size sorter.
Collect and publish actual window-size histograms before proposing more
complex bin packing.

**2. Fundamental physical-size limit — reordering is not magic.** Two
~2072B payloads plus metadata cannot fit in a 4096B V3 container, no matter
how perfectly sorted. Multi-block 8/16KiB extents mitigate this, but
some logical reads touch additional blocks and metadata, and real devices
can prefer different request sizes. An algorithm optimized only for byte
packing need not minimize device service time. 4KiB is V3's current
format unit, not a universal physical sector.

**3. Garbage collection creates necessary extra I/O.** Codex measured
compressed churn with **7,639,040B lower writes / 7,344,128B logical
writes = 1.040x**, including **294,912B GC writes**, and raw churn with
**8,392,704B / 7,344,128B = 1.143x**, including **1,048,576B GC
writes**. Both workloads had GC reads as well. These are *write
amplification relative to logical writes*, NOT proof that V3 is worse
than V2.2: there was **no identically loaded V2.2 control**. GC selects
a low-live-count victim rather than necessarily the victim with lowest
live *bytes* and relocation read/write cost. Its policy deserves
controlled comparison, but the report does not isolate GC selection as
the measured root cause.

**4. Real implementation/correctness defects.** Codex observed
`sv3_worker hogged CPU for >10000us` up to a reported 19 warnings,
and false “GC disabled” status. Main-developer code review later found
a **serious unused GC exclusion invariant**: the paused foreground OPEN
segment and current victim were not excluded from relocation allocation.
The alpha.2 branch added those protections, finite worker scheduling,
raw-page CRC, truthful status and optional readback. These are coding
errors/hardening deficits that affect readiness but **do not establish
that size-classed packing is algorithmically inferior**. The corrected
alpha.2 must be loaded and tested anew; a green build is insufficient.

**5. Release evidence missing, not a measured failure.** No paired
loaded V2.2-vs-V3 run on the same device and same *achieved* workload,
no explicit loaded `REQ_FUA` fail-order proof, no qualified physical
SD/SSD/HDD test, no long-run safety demonstration of the rebuilt alpha.2.
The alpha currently enforces `null_blk`-only backing. CPU timing on
memory-backed `null_blk` does not predict SD/SSD/HDD p99; host sector
statistics cannot reveal flash NAND program/erase operations.

## Engineering decisions, in order

1. **Correctness before optimization.** Independently qualify the actual
   rebuilt V3 module, GC forbidden-segment safety, fail-closed reads/writes,
   FUA/drain, raw integrity, workload concurrency and clean teardown.
2. **Instrument real packing opportunity.** Record write-window occupancy,
   actual LZ4 object-size distributions, class selection, pad bytes,
   size-compatible missed pairings, 4/8/16KiB extent selections, request
   splits/merges and GC time. Compare controlled low-QD and bursty loads.
3. **Optimize the staging pipeline, not just the sorter.** Test bounded
   size-class waiting queues across producer/worker turns, a finite
   batching deadline and/or overlap of compression/staging with lower
   I/O. Every change must preserve exactly-once upper completion, fresh
   reads, generation authority, FUA/flush/overwrite/discard ordering and
   bounded memory/latency. Never postpone swap reads just to fill a bin.
4. **Make cost/device-aware choices.** Compare 4KiB-first packing with
   8/16KiB extents under observed logical/physical sector geometry,
   minimum/optimal transfer size, real read cost, GC relocation cost,
   p99 and achieved IOPS. Use bytes+requests, not “4KiB operation counts.”
5. **Compare against a real control.** Load V2.2 and V3 *sequentially*
   (same module filename, incompatible format), with identical owned
   backing and payload fixtures, equal achieved reader/writer rates and
   independent device deltas. Attribute changes to window occupancy,
   packing, GC and CPU, rather than assuming the theoretical ordered4
   baseline represents loaded V2.2.
6. **Only then qualify physical target media.** The existing null_blk-only
   safety restriction cannot be bypassed to manufacture SD/SSD/HDD evidence.
   Physical-media access requires the release gates, isolated backing,
   exact source/module identity and absolutely **no reboot**.

## Classification

- **Fundamental constraint:** Some compressed object pairs do not fit in
  4KiB including metadata; read cost grows when records span units.
- **Algorithm/policy weakness:** bounded greedy reordering and an adaptive
  4/8/16KiB packer cannot profit from absent concurrent candidates;
  low-live-record-count GC is not proven to minimize relocation *bytes*.
- **Implementation issues:** singleton-window scheduling under actual
  arrival rates, workqueue CPU hog, missing GC forbidden-segment
  enforcement, formerly missing raw CRC/readback and false status strings.
- **Evidence gap:** no controlled loaded V2.2 improvement and no physical
  storage qualification, no proven alpha.2 loaded-kernel result.

**Decision:** preserve zsmalloc-inspired size-class packing as an
engineering hypothesis supported by demonstrated *loaded-kernel*
packing. Do not call it production-successful OR fundamentally failed
until the driver is correct and the I/O frontier is measured on the
same verified actual device against the real V2.2 baseline.
