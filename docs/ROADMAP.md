# Roadmap

**Immutable naming policy (read before every prompt):** The project is `swapz`; the kernel module is `dm-swapz.ko` (loaded as `dm_swapz`); the Device Mapper target is exactly `swapz`; and the module alias is `dm-swapz`. Never put implementation-generation numbers in product, module, target, source-path, report, workflow, helper, or schema names. `SWZ3` is reserved for the on-disk format identity.

**Single official test command (read before every prompt):** Run `make test` at the repository root for every supported swapz test and benchmark. A complete run must report BLOCKED (nonzero) if safe noninteractive privileged qualification cannot run. Do not create, publish, recommend, or document alternative test commands. Private scripts and CI jobs are implementation details, not operator interfaces.

This file contains only active work. Completed experiments and detailed historical transcripts belong in Git history.

## Current baseline

Owner qualification of `4edf2d60a9275fb9e57e7eb605bce6c02c2a1263`
passed all five stages; report-only commit
`70dea7aa36611df541823b711f918d78c4f4a163` is the canonical result. These
remain owned-RAM `null_blk` synthetic models, not physical-media claims.

ID52 answered its diagnostic question. On the fast mixed model 107.5 deferred
singletons resolve as 76.0 companions and 31.5 one-page deadlines. Companion
ages are 52.8/19.0/3.2/1.0 in <=250/251-500/501-1000/>1000 us bins, while all
31.5 deadline resolutions are >1000 us. Lower-W completion and READ bypass
occur in both terminal classes, so service events are rejected as close
discriminators. Age is the only clean discriminator in this evidence.

ID53 is the bounded successor experiment. Only a sampled singleton already in
`retained_single_tail_deferred` may use an effective deadline of
`min(original deadline, deferred start + 1 ms)`. It reuses the existing
retention hrtimer; a companion restores the ordinary deadline. The experiment
counts age-cutoff closes and a next-WRITE-before-original-deadline
`late_companion` miss signal. Cutoff closes must not train the unrelated
full-deadline singleton fast-close heuristic.

ID39 now has controlled same-source/same-cache evidence in its favor. Kread-off
versus Kread-on fast p99 is 5.57/5.21 ms sequential and 5.65/4.98 ms random,
while lower traffic is effectively unchanged/slightly lower and Kread-on
executes about 333 parallel pairs. This is two observations per mode, so the
mechanism remains pending >=5 matched confirmation rather than policy changes.

ID50 remains Class 4. The latest fast mixed async/sync result is 23.72/22.27
MB/s with 905.5/925 lower WRITE requests, while write-only QD8 is
28.27/20.65 MB/s async/sync with 524 lower requests. These are encouraging
directional results, but mixed still has two observations per mode and
write-only one pair per point. Repeated matched evidence is the next gate.

Existing fast mixed 2-4-record windows are 158.0 async versus 149.5 sync, only
about a 5.7% excess. That is not enough to justify another multi-tail hot-path
histogram or policy. Keep the existing window bins while repeated runs determine
whether the excess persists.

## Current bottleneck ranking

These overlapping wall counters are diagnostic, not additive. In the latest
mixed run lower WRITE remains the largest measured WRITE-path wall at about
601.7 ms slow / 177.0 ms fast. LZ4 preparation is 140.8/77.4 ms and commit
non-I/O is 54.9/36.6 ms. Snapshot pause CRC remains only 1.7/1.1 ms; planner and
explicit copy costs are secondary.

READ amplification is no longer the active defect. The shared extent cache is
qualified independently, and the same-cache toggle now shows Kread improving
both sequential and random p99 without traffic inflation. The remaining READ
gate is statistical repeatability, not another concurrency redesign.

WRITE fragmentation is now narrower. ID50 still removes sampled-tail one-page
PACK_READY closes; in the latest fast mixed run async uses 905.5 lower WRITE
requests versus 925 sync while reaching 23.72 versus 22.27 MB/s. Run-to-run
variation remains large enough that the >=5 matched-pair gate is mandatory.
ID53 tests only whether the measured >1 ms true-tail cluster can be shortened
without losing companions or inflating requests.

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
| 12 | Split stage/pause hash/hole-clear/control residual | **1 completed snapshot measurement** | Reconfirmed at ~1.7/1.1 ms pause with ~8.6/6.2 ms residual after subtraction. Full-transaction hashing stays; the snapshot-scope optimization question is closed. Further residual splitting is optional attribution only. |
| 13 | Dry PACK_READY close -> next accepted WRITE timing | **1 completed measurement** | Question answered and telemetry deleted. |
| 14 | Extra preparation credits in current synchronous geometry | **5** | Serial lower-WRITE preparation backlog is still 0.00/0.00; fast is only 0.18/0.06. Generic extra credits cannot manufacture enough eligible work. |
| 15 | >=5 counterbalanced pairs for mixed/QD points | **4 evidence collection ready** | Decisive WRITE-policy gate. Latest fast QD8 is +36.9% async/sync and fast mixed is +6.5%, but current samples are still one pair/QD and two observations/mode. Run >=5 matched fast QD8 and mixed pairs with paired uncertainty before promotion. |
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
| 37 | K=1 ping-pong WRITE pipeline | **4 confirmation pending** | Latest fast write-only QD8 is +36.9% async/sync with 524 lower requests and QD32 is +9.1% with 139; fast mixed is +6.5%. Keep opt-in and change no scheduling until >=5 matched confirmation. |
| 38 | Shared accumulator with K>1 lower-write slots | **5** | Stronger hold. Serial hwq=1 has no parallel service slot. Fast hwq=64 has capacity, but K=1 run occupancy is only ~0.09 and preparation backlog is shallow; there is no sustained ready-run pressure for K>1 yet. |
| 39 | Latency-first bounded parallel READ service | **4 confirmation pending** | Same-cache Kread-on improves fast sequential p99 5.57 -> 5.21 ms and random 5.65 -> 4.98 ms with unchanged/slightly lower traffic and positive parallel activity. Repeat >=5 matched toggles before promotion. |
| 40 | Freeze first, then start LZ4/CRC | **5** | Rejected; compression belongs during collection. |
| 41 | Per-lane isolated write accumulators / 2xN packing queues | **5** | Reject by default; destroys global packing view and risks request inflation. |
| 42 | Explicit serial-vs-parallel lower queue model + lower in-flight-depth telemetry | **1 completed measurement** | Owner-qualified. Slow hwq=1 stays at sampled peak depth 1; fast raw reaches >1 while swapz remains at 1. Keep the geometry and telemetry as mandatory evidence for concurrency claims. |
| 43 | Huge/compound-page RAM input support (folio/THP/hugetlb), not only 4KiB page inputs | **4 evidence/coverage** | bio_for_each_segment() already page-normalizes multi-page bvecs; current copies are page-local and page-aligned 4KiB folio slices can direct-map. Do not add nth_page() to iterator bvecs. Add explicit THP/folio coverage; larger base PAGE_SIZE/native larger records remain architecture work. |
| 44 | Exact per-segment authoritative mapping counts / GC map-scan elimination | **1** | Owner-qualified with 20 live victims/rotations and byte-exact 4096-page verification. Keep O(1) dead-segment/post-evacuation checks; victim scoring/evacuation reverse indexing remains a separate future optimization. |
| 45 | 4-block extent payload block-residency cache | **1** | Owner-qualified; keep. Slow packed sequential p99 improved to 16.85 ms with 3056 KiB / 457.5 lower requests, and native C proves each block of a seven-record 16KiB extent is fetched at most once before invalidation. |
| 46 | Timed-interval scheduling telemetry hygiene | **1 completed measurement** | Qualified. Mixed/write-only scheduling conclusions now use kernel snapshots strictly around measured waves; full-process prefill/warmup counters are not evidence. |
| 47 | Explicit ordering-boundary singleton reset | **1** | Qualified correctness/measurement hygiene. PREFLUSH/FUA/discard/shutdown/other reset learned singleton state, including empty fsync PREFLUSH; ordinary idle/deadline closes do not. |
| 48 | Fast mixed one-page PACK_READY cause attribution | **1 completed measurement** | Repaired-read confirmation is 78.0 tail-target / 24.2 read-bypass / 0 wave-interruption, with slow 0/0/0. Sampled singleton tails remain dominant; read-bypass/wave as the primary root cause is refuted. |
| 49 | 16-entry shared multi-extent READ residency cache | **1** | Reconfirmed again on hwq=1: 2830 KiB / 400.5 requests / 14.33 ms sequential and 2498 KiB / 624.5 / 22.21 ms random. Keep the 256KiB ordered-owner cache and exact invalidation. |
| 50 | Sampled-single-tail PACK_READY deferral | **4 mechanism strongly supported; policy pending repeated evidence** | Latest fast D/C/DL/I/O is 107.5/76.0/31.5/0/0. Keep ID50; ID53 tests only a measured age bound for the true-tail subset rather than service-event closure. |
| 51 | Deferred-singleton outcome attribution | **1 completed measurement** | Reconfirmed fast D/C/DL/I/O = 107.5/76.0/31.5/0/0 with exact conservation. Retain counters through the ID53/ID50 decision. |
| 52 | Deferred-singleton timing/service discrimination | **1 completed measurement** | Age separates strongly: 75/76 fast companions resolve within 1 ms while every observed deadline tail is >1 ms. Lower-W completion and READ bypass occur in both classes and are rejected as discriminators. |
| 53 | 1 ms deferred-singleton age cutoff | **4 bounded experiment implemented pending owner evidence** | Only ID50's deferred sampled singleton gets the shorter effective deadline. Reuse the existing hrtimer, preserve the original deadline as hard upper bound, count cutoff closes and late would-be companions, and reject on request/latency/correctness regression. |


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

1. Owner-qualify ID53 together with the strengthened evidence matrix. Reject the
   1 ms cutoff if late-companion misses are material, lower WRITE
   bytes/requests rise materially, useful throughput/read tails regress, or any
   lifecycle/order gate fails.
2. Promote ID39 only if >=5 same-cache matched Kread toggles retain the latency
   advantage with unchanged lower traffic. Change no READ algorithm meanwhile.
3. Use >=5 matched fast write-only QD8 and mixed QD32 observations to decide
   K=1 ping-pong/ID50. Keep QD1/QD4/QD32 directional controls and do not add a
   new WRITE scheduling heuristic before this gate.
4. Collect trustworthy kernel-worker on-CPU attribution before N=2 preparation
   workers or CPU-topology changes; keep K>1 lower-WRITE slots rejected.
5. Then run bounded owned-RAM dead-segment DISCARD/TRIM, huge/compound-page
   coverage and heavy-CPU/low-RAM qualification.

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
