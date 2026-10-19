# Roadmap

**Immutable naming policy (read before every prompt):** The project is `swapz`; the kernel module is `dm-swapz.ko` (loaded as `dm_swapz`); the Device Mapper target is exactly `swapz`; and the module alias is `dm-swapz`. Never put implementation-generation numbers in product, module, target, source-path, report, workflow, helper, or schema names. `SWZ3` is reserved for the on-disk format identity.

**Single official test command (read before every prompt):** Run `make test` at the repository root for every supported swapz test and benchmark. A complete run must report BLOCKED (nonzero) if safe noninteractive privileged qualification cannot run. Do not create, publish, recommend, or document alternative test commands. Private scripts and CI jobs are implementation details, not operator interfaces.

This file contains only active work. Completed experiments and detailed historical transcripts belong in Git history.

## Current baseline

Owner qualification of `89fe7116b8800b417b351f32a7305b3ed7abd261`
passed all five stages; the canonical report was published as report-only commit
`179c66b8fa975677f6426de5ebc511ad72d608ef`. These remain owned-RAM
`null_blk` synthetic models, not physical-media claims.

The timed-boundary correction removed prefill, warmup and packed-read population
from scheduling evidence. On the serial-depth slow model, measured mixed QD32
now has zero one-page PACK_READY closes, zero one-page deadline closes and zero
worker-empty deadlines. Its async useful WRITE remains 7.05 MB/s versus 2.68
raw while lower WRITE requests fall from 12301 to about 544.5. The product gain
therefore remains compression/global aggregation, not extra WRITE concurrency.

The faster depth-64 model reaches 22.32 MB/s async WRITE versus 21.78 sync and
19.24 raw. Async remains NO_SIGNIFICANT_ASYNC_GAIN versus sync and uses about
932.5 lower WRITE requests versus 853.5 sync. K=1 slot occupancy remains about
0.09 of mixed wall. Write-only QD8 still has a positive but directional +12.3%
async/sync signal; QD1 is -10.1%, QD4 -1.0% and QD32 +1.6%. No K>1 WRITE work
is justified before repeated matched pairs.

Clean timed telemetry exposes a model-specific retained-window issue rather than
a global one. Faster mixed QD32 records about 89 one-page PACK_READY closes,
29.8 one-page deadline closes and 50.2 worker-empty deadlines per pair, while
the serial model records zero for all three. The next instrumentation attributes
every one-page PACK_READY close to sampled tail, retained read-bypass or wave-
interruption evidence before any closure policy changes.

The 4-block payload-residency cache is owner-qualified and retained. Slow packed
sequential reads are 3056 KiB / 457.5 lower requests with 16.85 ms p99 and
random reads 2528 KiB / 632 requests with 22.79 ms p99; both beat raw latency.
Fast packed reads still report NOT_FASTER despite lower bytes/requests: sequential
3358 KiB / 548.5 requests / 5.01 ms p99 and random 2480 KiB / 620 requests /
5.22 ms p99. Raw fast READ depth reaches about 3.8 while swapz remains at one,
so bounded latency-first READ parallelism is the next concurrency experiment.

Snapshot CRC attribution is now measurable but still combines two accounting
regions: total pause+resume snapshot CRC is about 3.3 ms slow / 2.4 ms fast;
pause belongs to commit residual while resume is already inside publish. The
next source splits those two counters while preserving the exact full-
`struct swapz_tx` hash. No active-prefix hash change is qualified yet.

Loaded live GC again passes with 20 victims, 20 rotations, 20 distinct victim
segments, 1/1 min/max evictions and byte-exact verification of all 4096 logical
pages. The rejected bound-worker, overlap-as-objective, grace-timer, freeze-
then-compress and iterator-side `nth_page()` experiments remain rejected.

## Current bottleneck ranking

These wall counters overlap and must not be added as if they formed one serial
timeline. The table ranks measured mixed-WRITE cost/importance from the
`89fe711...` owner run, not an additive runtime budget. Snapshot CRC pause and
resume are not yet separately measured in this baseline.

| Rank | Serial-depth slow model | Wall | Parallel-depth fast model | Wall | Interpretation |
|---:|---|---:|---|---:|---|
| 1 | Lower WRITE wall | **603.5 ms** | Lower WRITE wall | **185.5 ms** | Dominant measured WRITE-path wall; K=1 occupancy is still shallow. |
| 2 | LZ4 preparation | **141.3 ms** | LZ4 preparation | **79.6 ms** | Largest CPU preparation phase. |
| 3 | Commit non-I/O total | **54.4 ms** | Commit non-I/O total | **40.3 ms** | Serialized CPU/control envelope. |
| 4 | Publish total | **22.8 ms** | Publish total | **18.1 ms** | Includes resume snapshot CRC plus finish/publication work. |
| 5 | Pack | **15.0 ms** | Pack | **10.0 ms** | Material but below LZ4/lower I/O. |
| 6 | Payload CRC during preparation | **14.8 ms** | Publish authority/liveness | **9.1 ms** | Integrity/control work remains secondary. |
| 7 | Final-image publish CRC | **12.0 ms** | Final-image publish CRC | **9.0 ms** | Mandatory final immutable-image integrity boundary. |
| 8 | Publish authority/liveness | **10.8 ms** | Payload CRC during preparation | **8.3 ms** | Authority includes resume snapshot hashing in this baseline. |
| 9 | Commit residual before pause split | **10.2 ms** | Commit residual before pause split | **7.7 ms** | Contains pause snapshot CRC plus other stage/control work; the candidate splits it. |
| 10 | Planner | **6.4 ms** | Planner | **4.6 ms** | Not a planner-rewrite target. |
| 11 | Explicit RAM copies | **5.0 ms** | Explicit RAM copies | **3.5 ms** | Too small to justify complex copy/DMA work. |

Packed READ lower wall remains dominant over CPU: about 487.7/672.3 ms slow
sequential/random versus 7.1/7.8 ms engine non-I/O, and 105.1/119.1 ms fast
versus 6.2/6.7 ms engine non-I/O. Fast raw READs reach sampled depth about 3.8
while swapz remains at one; Kread=2 is intended to test that queue-depth gap.

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
| 12 | Split stage/pause hash/hole-clear/control residual | **4 instrumentation refined pending owner evidence** | Total snapshot CRC is ~3.3/2.4 ms but crosses accounting regions. Pause and resume now have separate timers while the full-struct hash remains unchanged; only pause may be reconciled out of commit residual. |
| 13 | Dry PACK_READY close -> next accepted WRITE timing | **1 completed measurement** | Question answered and telemetry deleted. |
| 14 | Extra preparation credits in current synchronous geometry | **5** | Serial lower-WRITE preparation backlog is still 0.00/0.00; fast is only 0.18/0.06. Generic extra credits cannot manufacture enough eligible work. |
| 15 | >=5 counterbalanced pairs for mixed/QD points | **6** | Decisive WRITE-policy gate: mixed still has two pairs/mode and write-only one pair/QD. Fast QD8 is +12.3% async/sync while QD1 is -10.1%; do not promote a QD-sensitive policy without confidence intervals. |
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
| 31 | Shared descriptor queue + multiple unbound prep workers | **4 dependent** | Serial still has no preparation backlog and fast remains shallow (~0.21/0.06 at lower-WRITE boundaries). Consider N=2 only after repeated fast-QD8 evidence plus trustworthy on-CPU attribution. |
| 32 | One affinity-pinned worker per physical core | **3** | Reject affinity form. |
| 33 | Linux kernel CRC32C primitive | **1** | Already implemented; keep architecture-selected kernel backend. |
| 34 | Hand-selected SIMD/instructions beyond kernel/LZ4 | **6** | CRC is measurable, but verify active backend/on-CPU cost before bypassing kernel primitives. |
| 35 | Firmware/device/upper/lower compute offload | **6** | Hardware/interface dependent. |
| 36 | Heavy-CPU plus low-RAM qualification | **6** | Mandatory before multi-worker/pipeline promotion. |
| 37 | K=1 ping-pong WRITE pipeline | **4 conditional** | Serial mixed is neutral and fast mixed is only +2.5% while using more lower requests than sync. Fast write-only QD8 remains +12.3%, but QD1/QD4 regress. Keep opt-in pending >=5 matched pairs. |
| 38 | Shared accumulator with K>1 lower-write slots | **5** | Stronger hold. Serial hwq=1 has no parallel service slot. Fast hwq=64 has capacity, but K=1 run occupancy is only ~0.09 and preparation backlog is shallow; there is no sustained ready-run pressure for K>1 yet. |
| 39 | Latency-first bounded parallel READ service | **4 implemented pending owner evidence** | Duplicate-I/O baseline is now qualified. Production adds exactly Kread=2 with private slot engines/scratch, same-extent residency reuse, strict dependency gates, immediate service and ordered-owner join/merge. Fast raw reaches READ depth ~3.8 while swapz baseline is 1; slow hwq=1 must not regress. |
| 40 | Freeze first, then start LZ4/CRC | **5** | Rejected; compression belongs during collection. |
| 41 | Per-lane isolated write accumulators / 2xN packing queues | **5** | Reject by default; destroys global packing view and risks request inflation. |
| 42 | Explicit serial-vs-parallel lower queue model + lower in-flight-depth telemetry | **1 completed measurement** | Owner-qualified. Slow hwq=1 stays at sampled peak depth 1; fast raw reaches >1 while swapz remains at 1. Keep the geometry and telemetry as mandatory evidence for concurrency claims. |
| 43 | Huge/compound-page RAM input support (folio/THP/hugetlb), not only 4KiB page inputs | **4 evidence/coverage** | bio_for_each_segment() already page-normalizes multi-page bvecs; current copies are page-local and page-aligned 4KiB folio slices can direct-map. Do not add nth_page() to iterator bvecs. Add explicit THP/folio coverage; larger base PAGE_SIZE/native larger records remain architecture work. |
| 44 | Exact per-segment authoritative mapping counts / GC map-scan elimination | **1** | Owner-qualified with 20 live victims/rotations and byte-exact 4096-page verification. Keep O(1) dead-segment/post-evacuation checks; victim scoring/evacuation reverse indexing remains a separate future optimization. |
| 45 | 4-block extent payload block-residency cache | **1** | Owner-qualified; keep. Slow packed sequential p99 improved to 16.85 ms with 3056 KiB / 457.5 lower requests, and native C proves each block of a seven-record 16KiB extent is fetched at most once before invalidation. |
| 46 | Timed-interval scheduling telemetry hygiene | **1 completed measurement** | Qualified. Mixed/write-only scheduling conclusions now use kernel snapshots strictly around measured waves; full-process prefill/warmup counters are not evidence. |
| 47 | Explicit ordering-boundary singleton reset | **1** | Qualified correctness/measurement hygiene. PREFLUSH/FUA/discard/shutdown/other reset learned singleton state, including empty fsync PREFLUSH; ordinary idle/deadline closes do not. |
| 48 | Fast mixed one-page PACK_READY cause attribution | **4 instrumentation implemented pending owner evidence** | Faster mixed has ~89 timed one-page PACK_READY closes while slow has zero. Attribute every close mutually exclusively to sampled tail, retained read-bypass or wave interruption before changing closure policy. |

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

1. Owner-qualify bounded Kread=2. Require fast lower READ peak/depth and packed-read
   p99/useful throughput to improve without increased lower bytes/requests; the
   serial hwq=1 model must not regress. Same-extent pairs should demonstrate
   private-slot residency reuse.
2. Read the new ID 48 split. Do not change `swapz_retained_pack_close_ready()`
   unless one measured cause dominates the fast-model singleton PACK_READY
   population and a surgical change preserves write-only QD4/QD8/QD32 geometry.
3. Read the ID 12 pause/resume split. Reconcile only pause CRC out of commit
   residual. Keep full-transaction hashing until a separately reviewed active-
   prefix experiment is justified by the pause-side cost.
4. Run >=5 counterbalanced matched pairs for fast mixed QD32 and write-only
   QD1/QD8 before promoting or deleting K=1 WRITE scheduling.
5. Keep K=1 WRITE ping-pong opt-in and do not add K=2/4/8 lower-WRITE slots.
6. Add trustworthy kernel-worker on-CPU attribution before multi-worker or CPU-
   topology changes.
7. Run the bounded owned-RAM dead-segment DISCARD/TRIM experiment, then the
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
