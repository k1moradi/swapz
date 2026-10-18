# Roadmap

**Immutable naming policy (read before every prompt):** The project is `swapz`; the kernel module is `dm-swapz.ko` (loaded as `dm_swapz`); the Device Mapper target is exactly `swapz`; and the module alias is `dm-swapz`. Never put implementation-generation numbers in product, module, target, source-path, report, workflow, helper, or schema names. `SWZ3` is reserved for the on-disk format identity.

**Single official test command (read before every prompt):** Run `make test` at the repository root for every supported swapz test and benchmark. A complete run must report BLOCKED (nonzero) if safe noninteractive privileged qualification cannot run. Do not create, publish, recommend, or document alternative test commands. Private scripts and CI jobs are implementation details, not operator interfaces.

This file contains only active work. Completed experiments and detailed historical transcripts belong in Git history.

## Current baseline

Owner qualification of `5036137fa7cdbb155cf9b0189079011d49b74de3`
passed all five stages; the canonical report was published as report-only commit
`fd6d46fe5ba022bd6a744ceac260104324d1117d`. These remain owned-RAM
`null_blk` synthetic models, not physical-media claims.

The slow profile now explicitly uses blk-mq, one submit queue and
`hw_queue_depth=1`. Observed lower in-flight depth confirms the model is
actually serial: raw, sync and async all have sampled READ/WRITE peaks of one.
This changes the product-level conclusion. Mixed QD32 raw reaches only
2.68 MB/s WRITE + 0.89 MB/s READ, while swapz reaches 7.08/2.35 MB/s sync and
7.05/2.34 MB/s async. The same logical work drops from 12301 raw lower WRITE
requests to about 545-547 swapz requests. Compression plus global aggregation
therefore provides a large useful-throughput and lower-request benefit on this
high-latency serial-depth model.

The K=1 asynchronous WRITE policy is a separate result and does not explain that
gain. Slow async is -0.4% versus sync, LZ4 overlaps only ~0.2 ms of ~605.8 ms
lower-WRITE wall, the unclaimed preparation queue is 0.00/0.00 at lower-WRITE
start/end, and the immutable K=1 run slot is occupied only ~0.08 of mixed wall.
The core swapz data-reduction/aggregation path is valuable here; extra WRITE
pipeline concurrency is not.

The faster profile uses the same blk-mq/one-submit-queue setup with
`hw_queue_depth=64`. Mixed QD32 reaches 19.54/6.49 MB/s raw WRITE/READ,
21.63/7.18 sync and 22.45/7.45 async. Async is +3.8% versus sync for WRITE, but
the two-pair qualification still reports NO_SIGNIFICANT_ASYNC_GAIN. Lower WRITE
requests are ~883.5 sync and ~908 async versus 12301 raw. Observed raw lower
depth reaches about 4 READs and 6.2 WRITEs at sampled peak, while both swapz
modes remain near peak depth one. The K=1 immutable WRITE slot is occupied only
~0.09 of mixed wall, so adding more WRITE slots is not justified by current
ready-run pressure.

The strongest new parallel-service opportunity is instead on READs for the fast
model: raw demonstrates lower READ depth greater than one while swapz remains
serialized at one, and the packed-read verdict is NOT_FASTER. Any READ
concurrency experiment must keep private scratch, same-page dependency fences
and immediate idle-device dispatch so it cannot regress the serial model.

Write-only evidence remains directional. On the serial-depth model, swapz
strongly exceeds raw at QD4/QD8/QD32, but async preparation adds only
-0.7/+1.2/-0.3% versus sync. On the faster model, QD8 async remains the narrow
scheduling signal at +22.6% versus sync, yet 23.78 MB/s is still far below the
45.84 MB/s raw arm. One pair per QD cannot promote that policy.

Publication attribution remains stable. Slow publication is ~22.1 ms:
12.0 ms final-image CRC and 10.1 ms authority/liveness. Fast publication is
~17.2 ms: 8.8 ms CRC and 8.3 ms authority. Final CRC remains the largest single
publication subphase, not the end-to-end bottleneck. LZ4 preparation is
~140.4/80.0 ms slow/fast; total commit non-I/O is ~52.7/38.1 ms.

The unexplained commit residual is now ~9.3 ms slow / 6.8 ms fast. It remains
worth a bounded attribution split, but not at the expense of lower-I/O, READ
parallelism or LZ4-path evidence.

Packed reads also changed with the corrected queue model. The serial-depth
profile now qualifies FASTER: sequential p99 falls from 34.20 to 18.33 ms and
seeded-random from 34.31 to 23.67 ms while lower bytes/requests fall. The faster
profile improves numerically but remains NOT_FASTER under the qualification
gate. Read work must therefore remain latency-first and model-aware.

Loaded live GC again passes with 20 victims, 20 rotations, 20 distinct victim
segments, 1/1 min/max evictions, nonzero lower READ/WRITE traffic and byte-exact
verification of all 4096 logical pages. This is the first owner-loaded evidence
with exact per-segment authoritative mapping counts active.

The rejected `task_cputime_adjusted()` metric, CPU-local/bound preparation,
dry microsecond grace experiment, freeze-then-compress design and iterator-side
`nth_page()` folio rewrite remain rejected.

The next candidate is intentionally narrower than ID 39: it first removes
duplicate payload-block reads within one immutable 4-block extent, resets learned
singleton policy only at explicit ordering barriers, moves scheduling telemetry
to the exact measured interval, and measures the existing full-transaction
snapshot CRC. None of those changes adds parallel READ ownership, changes
PACK_READY closure policy, or shortens the transaction hash.

## Current bottleneck ranking

These wall counters overlap and must not be added as if they formed one serial
timeline. The table ranks measured mixed-WRITE cost/importance, not an additive
runtime budget.

| Rank | Serial-depth slow model | Wall | Parallel-depth fast model | Wall | Interpretation |
|---:|---|---:|---|---:|---|
| 1 | Lower WRITE wall | **605.8 ms** | Lower WRITE wall | **179.4 ms** | Still the largest measured WRITE-path wall. On slow hwq=1 the product gain comes from data/request reduction, not async overlap; on fast, K=1 slot occupancy is only ~9%, so more WRITE slots are not yet justified. |
| 2 | LZ4 preparation | **140.4 ms** | LZ4 preparation | **80.0 ms** | Largest CPU preparation phase and increasingly important on the faster model. |
| 3 | Commit non-I/O total | **52.7 ms** | Commit non-I/O total | **38.1 ms** | Serialized CPU/control budget; bounded attribution still useful. |
| 4 | Publish total | **22.1 ms** | Publish total | **17.2 ms** | Largest commit subphase. |
| 5 | Pack | **15.1 ms** | Pack | **9.8 ms** | Material but already well below LZ4/lower I/O. |
| 6 | Payload CRC during preparation | **14.6 ms** | Final-image publish CRC | **8.8 ms** | Both are material integrity work; neither is the end-to-end bottleneck. |
| 7 | Final-image publish CRC | **12.0 ms** | Publish authority/liveness | **8.3 ms** | Final CRC remains mandatory; authority cost is similar on fast. |
| 8 | Publish authority/liveness | **10.1 ms** | Payload CRC during preparation | **8.2 ms** | Same order of magnitude as CRC on the faster model. |
| 9 | Commit residual | **9.3 ms** | Commit residual | **6.8 ms** | Still unexplained enough for a bounded split, especially on slow. |
| 10 | Planner | **6.3 ms** | Planner | **4.4 ms** | Not a planner-rewrite target. |
| 11 | Explicit RAM copies | **5.1 ms** | Explicit RAM copies | **3.5 ms** | Still too small to justify complex copy/DMA work. |

For packed reads, lower READ wall remains dominant over engine work:
~490/675 ms slow sequential/random versus ~7.4/7.7 ms engine non-I/O, and
~100/118 ms fast versus ~5.6/6.8 ms engine non-I/O. The new queue telemetry
adds an important distinction: fast raw READs reach sampled depth >1 while
swapz READs remain at depth one.

## Optimization evidence table

Classes are evidence states: **(1)** tested-valid/keep, **(2)** tested-invalid
because the implementation or metric cannot answer the intended question,
**(3)** tested-invalid despite a sound experiment, **(4)** ready for a bounded
experiment/evidence collection, **(5)** refuted/not worth implementing from
current evidence, and **(6)** architecture/deployment/evidence gate rather than
an immediately qualified optimization. IDs are stable even when priority
changes.

| ID | Idea | Class | Current decision |
|---:|---|---|---|
| 1 | Direct single-bvec BIO -> LZ4 input | **1** | Qualified; keep the owned-page direct input and fallback. |
| 2 | Commit plan/pack/publish attribution | **1** | Qualified; keep. |
| 3 | Global serialized publication/authority on one shared backing device | **1** | Keep correctness authority; pipeline preparation/I/O around it rather than splitting it. |
| 4 | `WQ_UNBOUND` preparation placement | **1** | Qualified placement; scheduler load-balancing remains preferred to affinity. |
| 5 | Inline RAW no-bounce staging | **1** | Qualified; copy cost remains small. |
| 6 | `task_cputime_adjusted()` callback CPU attribution | **2** | Rejected metric and deleted. |
| 7 | CPU-local/bound preparation worker | **3** | Rejected and deleted. |
| 8 | Maximize LZ4/lower-I/O overlap as the objective | **3** | Stronger rejection: serial swapz gains massively with only ~0.2 ms overlap, while fast overlap is ~4.8 ms and async still has no significant mixed gain. Optimize useful work/lower traffic, not overlap counters. |
| 9 | Precompute payload CRC during preparation | **1** | Qualified; keep. |
| 10 | Validate immutable metadata once during finish | **1** | Qualified; keep. |
| 11 | Split final-image publish CRC from authority/liveness | **1 completed measurement** | Reconfirmed: final CRC is 12.0/22.1 ms slow and 8.8/17.2 ms fast. It is a major publish subphase, not the global bottleneck. |
| 12 | Split stage/pause hash/hole-clear/control residual | **4 instrumentation implemented pending owner evidence** | The unchanged full-struct pause/resume transaction CRC now has its own wall counter. Use the next owner run to determine whether snapshot hashing materially explains the ~9.3/6.8 ms residual before considering active-prefix hashing. |
| 13 | Dry PACK_READY close -> next accepted WRITE timing | **1 completed measurement** | Question answered and telemetry deleted. |
| 14 | Extra preparation credits in current synchronous geometry | **5** | Serial lower-WRITE preparation backlog is still 0.00/0.00; fast is only 0.18/0.06. Generic extra credits cannot manufacture enough eligible work. |
| 15 | >=5 counterbalanced pairs for mixed/QD points | **6** | Now the decisive gate: mixed still has two pairs/mode and write-only one pair/QD. Fast QD8 +22.6% async/sync and fast mixed +3.8% must not be promoted without confidence intervals. |
| 16 | N=2/4 preparation workers in old single-credit design | **5** | Refuted as formulated. |
| 17 | Pointer handoff solely to remove current copies | **5** | Reconfirmed: explicit copies are only ~5.1 ms slow / 3.5 ms fast. |
| 18 | Rewrite bounded DP planner | **5** | Reconfirmed: planner is ~6.3 ms slow / 4.4 ms fast and is not dominant. |
| 19 | Skip final publish payload CRC | **5** | Rejected despite measured cost; final immutable-run integrity boundary is mandatory. |
| 20 | Remove batch pause/resume transaction CRC immediately | **5** | No isolated evidence justifies weakening snapshot protection. |
| 21 | Direct LZ4 decompression into read BIO | **5** | Reconfirmed: read-copy wall is ~1.1-1.4 ms while lower READ wall is ~100-675 ms. |
| 22 | DMA/hardware offload for current 4KiB copies | **5** | Wrong bottleneck. |
| 23 | Per-CPU independent authorities on one shared device | **5** | Reject; fragments ordering, GC and global packing. |
| 24 | Trustworthy kernel-worker on-CPU attribution | **6** | Priority rises on the fast model: lower WRITE/K=1 occupancy is shallow while write-only low/mid-QD still trails raw. Callback wall is not CPU time, so trustworthy on-CPU evidence is required before CPU-topology changes. |
| 25 | Async lower-I/O state machine with immutable run ownership | **1** | Owner-loaded qualification reconfirms the ownership/publication machinery. Keep the infrastructure; K=1 scheduling policy remains separate. |
| 26 | NUMA-local preparation domains | **6** | Hardware-blocked. |
| 27 | One swapz target per NUMA node with node-local backing | **6** | Deployment topology only. |
| 28 | Sustained live-GC workload | **1** | Reconfirmed with exact mapping counts active: 20 victims/rotations, 20 distinct victims and 4096 verified pages. |
| 29 | Dead-segment DISCARD/TRIM | **4** | Synthetic victim distribution remains qualified; bounded owned-RAM experiment is ready. |
| 30 | Tiny microsecond grace timer | **5** | Refuted and deleted. |
| 31 | Shared descriptor queue + multiple unbound prep workers | **4 dependent** | Serial model still has no preparation backlog. Fast has only 0.18/0.06 queued at lower-WRITE boundaries, but QD8 async remains +22.6% vs sync. Consider N=2 only after >=5 fast-QD8 pairs and on-CPU attribution; do not generalize. |
| 32 | One affinity-pinned worker per physical core | **3** | Reject affinity form. |
| 33 | Linux kernel CRC32C primitive | **1** | Already implemented; keep architecture-selected kernel backend. |
| 34 | Hand-selected SIMD/instructions beyond kernel/LZ4 | **6** | CRC is measurable, but verify active backend/on-CPU cost before bypassing kernel primitives. |
| 35 | Firmware/device/upper/lower compute offload | **6** | Hardware/interface dependent. |
| 36 | Heavy-CPU plus low-RAM qualification | **6** | Mandatory before multi-worker/pipeline promotion. |
| 37 | K=1 ping-pong WRITE pipeline | **4 conditional** | Owner evidence collected after the READ-fence fix. Serial mixed is 7.05 vs 7.08 sync (-0.4%); fast mixed is +3.8% but NO_SIGNIFICANT_ASYNC_GAIN. Fast write-only QD8 remains +22.6% vs sync but far below raw. Keep opt-in pending >=5 matched pairs. |
| 38 | Shared accumulator with K>1 lower-write slots | **5** | Stronger hold. Serial hwq=1 has no parallel service slot. Fast hwq=64 has capacity, but K=1 run occupancy is only ~0.09 and preparation backlog is shallow; there is no sustained ready-run pressure for K>1 yet. |
| 39 | Latency-first READ busy-time queue | **4 high priority, after duplicate-I/O baseline** | Raw READ peak is ~4 while swapz remains peak 1, but first qualify the new 4-block residency cache so parallel READ service is not used to hide avoidable duplicate lower reads. Private scratch, same-page fences and idle bypass remain mandatory for the later concurrency prototype. |
| 40 | Freeze first, then start LZ4/CRC | **5** | Rejected; compression belongs during collection. |
| 41 | Per-lane isolated write accumulators / 2xN packing queues | **5** | Reject by default; destroys global packing view and risks request inflation. |
| 42 | Explicit serial-vs-parallel lower queue model + lower in-flight-depth telemetry | **1 completed measurement** | Owner-qualified. Slow hwq=1 stays at sampled peak depth 1; fast raw reaches >1 while swapz remains at 1. Keep the geometry and telemetry as mandatory evidence for concurrency claims. |
| 43 | Huge/compound-page RAM input support (folio/THP/hugetlb), not only 4KiB page inputs | **4 evidence/coverage** | bio_for_each_segment() already page-normalizes multi-page bvecs; current copies are page-local and page-aligned 4KiB folio slices can direct-map. Do not add nth_page() to iterator bvecs. Add explicit THP/folio coverage; larger base PAGE_SIZE/native larger records remain architecture work. |
| 44 | Exact per-segment authoritative mapping counts / GC map-scan elimination | **1** | Owner-qualified with 20 live victims/rotations and byte-exact 4096-page verification. Keep O(1) dead-segment/post-evacuation checks; victim scoring/evacuation reverse indexing remains a separate future optimization. |
| 45 | 4-block extent payload block-residency cache | **4 implemented pending owner evidence** | Production now remembers exactly which 4KiB blocks of the current immutable extent were successfully fetched, so sibling reads can avoid duplicate payload I/O. Native C proves a seven-record 16KiB extent reads each physical block at most once and mutation invalidation clears residency. Owner packed-read lower-I/O/latency evidence is still required. |

## What the pinned queue experiment establishes

The QD32 replay remains intentionally unpaced and closed-loop, but the lower
device geometry is no longer ambiguous. The slow model is blk-mq with one
submit queue and `hw_queue_depth=1`, and observed lower peaks stay at one.
The faster model uses `hw_queue_depth=64`; raw traffic reaches sampled depth
greater than one, proving that the model can expose parallel lower service.

This resolves the earlier SD-model uncertainty. On the serial-depth synthetic
model, swapz's compression and aggregation are strongly beneficial even though
K=1 async preparation is not. The correct conclusion is therefore not "more
WRITE concurrency is needed for SD-like media"; it is "data/request reduction
already wins on the serial model, while async WRITE concurrency currently adds
nothing measurable."

The fast model exposes a different problem. swapz lower READ and WRITE peaks
remain near one despite deeper raw service capability. For WRITEs, the K=1 run
slot is occupied only ~9% of mixed wall and preparation backlog is shallow, so
K>1 would add slots before proving ready-run pressure. For READs, raw reaches
sampled depth ~4 while swapz remains serialized at one; this is the cleaner
bounded concurrency opportunity.

## Huge/compound-page support roadmap

swapz must not permanently assume that useful RAM input arrives as one ordinary
4KiB physical page. Add explicit support for compound/folio-backed inputs,
including transparent huge pages and hugetlb-backed memory where the block path
can expose them.

The first implementation should **not** silently change SWZ3 format semantics:
retain 4KiB logical records, generations, CRC boundaries and random-read units,
but walk/map 4KiB slices of a larger folio directly and avoid bounce copies.
Qualification must cover nonzero bio_vec offsets, boundaries crossing a base
page within a compound allocation, partial BIOs where permitted, lifetime/
pinning rules, direct LZ4 input safety, low-memory reclaim and byte-exact
readback.

A later experiment may evaluate larger native logical records/extents (for
example 16KiB/64KiB or huge-page-aware super-windows). That is a format and
latency experiment, not merely an input optimization: it changes compression
opportunity, metadata density, selective read amplification, CRC scope,
recovery, GC movement and random swap-in cost. It requires separate evidence
before any on-disk-format change.

## Immediate work queue

1. Owner-qualify the timed-boundary hygiene, explicit ordering-barrier singleton
   reset and 4-block payload-residency cache. Use only timed
   `kernel_write_path` window/preparation counters when interpreting the run.
2. Compare packed-read lower READ bytes/requests and p99 against the
   `5036137...` baseline. If duplicate lower reads fall without regressions,
   retain ID 45 before introducing parallel READ ownership.
3. Use `batch_snapshot_crc_wall_ns` to split the remaining commit residual.
   Do not change the full-transaction hash scope unless the measured cost is
   material.
4. With clean timed window counters, determine whether one-page PACK_READY
   closes occur materially inside measured mixed QD32 before changing
   `swapz_retained_pack_close_ready()`.
5. Run >=5 counterbalanced matched pairs for fast mixed QD32 and write-only QD8
   before promoting or deleting K=1. Preserve pinned queue geometry and
   lower-depth telemetry.
6. Prototype latency-first parallel READ service only after the duplicate-I/O
   baseline is qualified; require private scratch, same-page dependency checks
   and immediate idle-device dispatch.
7. Add trustworthy kernel-worker on-CPU attribution before multi-worker or
   CPU-topology changes.
8. Keep K=1 WRITE ping-pong opt-in and do not add K=2/4/8 until repeated
   evidence shows sustained ready-run pressure or K=1 slot saturation.
9. Run the bounded owned-RAM dead-segment DISCARD/TRIM experiment, then the
   huge/compound-page coverage and heavy-CPU/low-RAM gates.

## NUMA / deployment topology

Preparation should become NUMA-local only after bounded multi-worker scaling is
proven. The preferred architecture is one preparation domain per memory-local
NUMA node (node-local LZ4 workmem/scratch/prepared pools, routed by source page
home), feeding one global ordered mapping/allocation/GC authority when all nodes
share one backing device. Do not equate a Linux NUMA node one-to-one with a
physical memory controller without hardware-specific topology evidence.

A fully independent `swapz` instance per NUMA node is a deployment topology,
not the default single-target design. It is appropriate to evaluate when each
NUMA node also has genuinely node-local backing storage (for example an NVMe
behind that node's PCIe root complex). If multiple nodes share one backing
device, preserve one global storage authority so extent packing, barriers,
physical allocation and GC do not fragment across independent writers.

## Release gates

A release or physical-media trial remains blocked until the same pinned source has repeated byte-exact loaded correctness, genuine lower error coverage, sustained GC, bounded resource behavior, acceptable read p95/p99 and CPU/RAM, statistically defensible matched performance, and an independent safety review. Physical-device admission is not part of the current roadmap implementation.
