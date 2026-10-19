# Roadmap

**Immutable naming policy (read before every prompt):** The project is `swapz`; the kernel module is `dm-swapz.ko` (loaded as `dm_swapz`); the Device Mapper target is exactly `swapz`; and the module alias is `dm-swapz`. Never put implementation-generation numbers in product, module, target, source-path, report, workflow, helper, or schema names. `SWZ3` is reserved for the on-disk format identity.

**Single official test command (read before every prompt):** Run `make test` at the repository root for every supported swapz test and benchmark. A complete run must report BLOCKED (nonzero) if safe noninteractive privileged qualification cannot run. Do not create, publish, recommend, or document alternative test commands. Private scripts and CI jobs are implementation details, not operator interfaces.

This file contains only active work. Completed experiments and detailed historical transcripts belong in Git history.

## Current baseline

Owner qualification of `bd3f5886b61a28667585ce13032f8e83065dce85`
passed all five stages; report-only commit
`571d99e69adfb2462e0047e155ea1e3022119908` is the canonical result. These
remain owned-RAM `null_blk` synthetic models, not physical-media claims.

The naive private-slot Kread=2 experiment answered the concurrency question but
failed the efficiency gate. Fast mixed lower READ peak rose from one to 2.0 and
fast packed random p99 improved to 3.58 ms, but packed lower traffic increased
materially: slow sequential/random became 4446/6546 KiB and 635.5/1017.5
requests; fast became 4916/6388 KiB and 738.5/1011 requests. The depth-one model
therefore regressed badly, and the fast latency win was bought with unacceptable
physical read amplification. That implementation is rejected.

The cause is architectural rather than evidence against READ concurrency itself:
private slots had no 512-entry metadata cache, shared no multi-extent residency
with the master, and coalesced only immediately adjacent siblings. The next ID39
candidate keeps one shared ordered-owner cache (512 metadata blocks plus 16
multi-block extents), primes private slots before dispatch, absorbs validated
residency after join, groups siblings across the already-admitted independent
READ prefix, and disables the slot path entirely when backing `nr_requests == 1`.

ID48 is now answered. Fast mixed one-page PACK_READY attribution is about
79.8 tail-target / 17.8 read-bypass / 0 wave-interruption per pair: sampled
one-record tails dominate, so the earlier read-bypass-focused closure hypothesis
is refuted. Keep closure policy unchanged while the read baseline is repaired,
then remeasure the same attribution before changing tail sampling.

ID12 is also narrowed. Snapshot CRC totals about 3.5 ms slow / 2.2 ms fast, but
pause contributes only 1.8/1.0 ms outside publish; resume is 1.7/1.2 ms already
inside publication. Residual after subtracting pause remains about 9.0/5.8 ms.
Keep full-`struct swapz_tx` hashing and attribute the remaining residual before
any hash-scope experiment.

WRITE evidence remains directional. Slow mixed async is 7.00 MB/s versus 6.95
sync and 2.68 raw with about 545.5 lower requests. Fast mixed async is 24.36
versus 24.51 sync and 19.94 raw, so async/sync is still not a qualified gain.
Fast write-only QD8 is +29.8% async/sync in one pair, while QD1/QD4/QD32 are
+5.9/+3.4/+2.4%; >=5 matched pairs remain mandatory before policy promotion.
Live GC, suspend/resume and fail-closed fault qualification remain green.

## Current bottleneck ranking

These overlapping wall counters are diagnostic, not additive. From the
`bd3f588...` mixed run, lower WRITE remains the largest measured WRITE-path
wall (605.2 ms slow / 183.2 ms fast), LZ4 preparation is 142.9/76.3 ms, and
commit non-I/O is 56.2/35.7 ms. Snapshot pause CRC explains only 1.8/1.0 ms;
the residual after that subtraction is still 9.0/5.8 ms. Planner and explicit
copy costs remain secondary.

READ evidence is more decisive: the naive Kread=2 path raised fast lower READ
depth to 2 but increased lower traffic up to ~1.6x. The next READ experiment
must preserve cache locality while retaining depth; additional WRITE slots are
still unsupported because K=1 occupancy is only about 0.10 and preparation
backlog remains shallow.

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
| 12 | Split stage/pause hash/hole-clear/control residual | **4 attribution continues** | Pause/resume split answered the snapshot question: pause is only ~1.8/1.0 ms, leaving ~9.0/5.8 ms residual after subtraction. Keep full-transaction hashing and split the remaining residual before optimizing. |
| 13 | Dry PACK_READY close -> next accepted WRITE timing | **1 completed measurement** | Question answered and telemetry deleted. |
| 14 | Extra preparation credits in current synchronous geometry | **5** | Serial lower-WRITE preparation backlog is still 0.00/0.00; fast is only 0.18/0.06. Generic extra credits cannot manufacture enough eligible work. |
| 15 | >=5 counterbalanced pairs for mixed/QD points | **6** | Decisive WRITE-policy gate. Fast QD8 is +29.8% async/sync in the latest one-pair pilot and other QDs are positive, but fast mixed async remains slightly below sync. Repeat >=5 matched pairs before policy promotion. |
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
| 37 | K=1 ping-pong WRITE pipeline | **4 conditional** | Latest fast write-only QD8 is +29.8% and all write-only QDs are directionally positive, but fast mixed async is 24.36 vs 24.51 sync and evidence remains one pair/QD. Keep opt-in pending >=5 matched pairs. |
| 38 | Shared accumulator with K>1 lower-write slots | **5** | Stronger hold. Serial hwq=1 has no parallel service slot. Fast hwq=64 has capacity, but K=1 run occupancy is only ~0.09 and preparation backlog is shallow; there is no sustained ready-run pressure for K>1 yet. |
| 39 | Latency-first bounded parallel READ service | **4 revised experiment implemented; naive form rejected** | `bd3f588...` proved depth-2 latency potential but failed lower-I/O/serial gates because private slots fragmented caches. Revised candidate gates depth-one media off, adds a 16-slot ordered-owner extent cache, primes/absorbs private slots, and groups same-extent followers across the ready independent-READ prefix. |
| 40 | Freeze first, then start LZ4/CRC | **5** | Rejected; compression belongs during collection. |
| 41 | Per-lane isolated write accumulators / 2xN packing queues | **5** | Reject by default; destroys global packing view and risks request inflation. |
| 42 | Explicit serial-vs-parallel lower queue model + lower in-flight-depth telemetry | **1 completed measurement** | Owner-qualified. Slow hwq=1 stays at sampled peak depth 1; fast raw reaches >1 while swapz remains at 1. Keep the geometry and telemetry as mandatory evidence for concurrency claims. |
| 43 | Huge/compound-page RAM input support (folio/THP/hugetlb), not only 4KiB page inputs | **4 evidence/coverage** | bio_for_each_segment() already page-normalizes multi-page bvecs; current copies are page-local and page-aligned 4KiB folio slices can direct-map. Do not add nth_page() to iterator bvecs. Add explicit THP/folio coverage; larger base PAGE_SIZE/native larger records remain architecture work. |
| 44 | Exact per-segment authoritative mapping counts / GC map-scan elimination | **1** | Owner-qualified with 20 live victims/rotations and byte-exact 4096-page verification. Keep O(1) dead-segment/post-evacuation checks; victim scoring/evacuation reverse indexing remains a separate future optimization. |
| 45 | 4-block extent payload block-residency cache | **1** | Owner-qualified; keep. Slow packed sequential p99 improved to 16.85 ms with 3056 KiB / 457.5 lower requests, and native C proves each block of a seven-record 16KiB extent is fetched at most once before invalidation. |
| 46 | Timed-interval scheduling telemetry hygiene | **1 completed measurement** | Qualified. Mixed/write-only scheduling conclusions now use kernel snapshots strictly around measured waves; full-process prefill/warmup counters are not evidence. |
| 47 | Explicit ordering-boundary singleton reset | **1** | Qualified correctness/measurement hygiene. PREFLUSH/FUA/discard/shutdown/other reset learned singleton state, including empty fsync PREFLUSH; ordinary idle/deadline closes do not. |
| 48 | Fast mixed one-page PACK_READY cause attribution | **1 completed measurement** | Latest fast mixed split is ~79.8 tail-target / 17.8 read-bypass / 0 wave-interruption. Tail sampling dominates; the earlier read-bypass-focused root cause is refuted. Preserve counters for one repaired-read-baseline confirmation before changing policy. |

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

1. Owner-qualify the cache-coherent, queue-gated ID39 revision. Depth-one must
   use zero parallel batches and recover the serialized packed-read baseline;
   depth-64 should retain READ peak >1 without increasing lower bytes/requests
   versus the qualified `89fe711...` cache baseline.
2. Re-read ID48 on that repaired READ baseline. Do not change PACK_READY policy
   yet. If tail-target still dominates, instrument/adjust tail sampling rather
   than the minority read-bypass branch.
3. Split the remaining ID12 9.0/5.8 ms residual into stage/control/hole-clear/
   allocation-validation buckets; keep full transaction snapshot hashing.
4. Run >=5 counterbalanced fast write-only QD8 pairs plus QD1 and mixed-QD32
   controls before promoting/deleting K=1 WRITE scheduling.
5. Collect trustworthy kernel-worker on-CPU attribution before N=2 preparation
   workers or CPU-topology changes; keep K>1 lower-WRITE slots rejected.
6. Then run bounded owned-RAM dead-segment DISCARD/TRIM, huge/compound-page
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
