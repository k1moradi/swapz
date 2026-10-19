# Roadmap

**Immutable naming policy (read before every prompt):** The project is `swapz`; the kernel module is `dm-swapz.ko` (loaded as `dm_swapz`); the Device Mapper target is exactly `swapz`; and the module alias is `dm-swapz`. Never put implementation-generation numbers in product, module, target, source-path, report, workflow, helper, or schema names. `SWZ3` is reserved for the on-disk format identity.

**Single official test command (read before every prompt):** Run `make test` at the repository root for every supported swapz test and benchmark. A complete run must report BLOCKED (nonzero) if safe noninteractive privileged qualification cannot run. Do not create, publish, recommend, or document alternative test commands. Private scripts and CI jobs are implementation details, not operator interfaces.

This file contains only active work. Completed experiments and detailed historical transcripts belong in Git history.

## Current baseline

Owner qualification of `5694d55e092a2d234d9466cce5416672db8b082e`
passed all five stages; report-only commit
`0490a84ef7515182a8db0bdf287ca598ccaf8674` is the canonical result. These
remain owned-RAM `null_blk` synthetic models, not physical-media claims.

ID50's mechanism is validated but the policy remains experimental. On the fast
mixed async arm, sampled-tail one-page PACK_READY closes fell from about 78 to
0 without moving into read-bypass/wave attribution (24.0/0.0), and lower WRITE
requests fell from 1005.5 to 952.5. The async/sync useful WRITE ratio remained
about 97.1% (22.95 vs 23.63 MB/s), while one-page deadline closes reached 53.2
and worker-empty deadlines 86.8. ID51 therefore attributes every deferred
singleton to companion, deadline, idle or other terminal resolution before any
second policy change.

ID49 remains independently qualified. With hwq=1 and parallel READ service
disabled, packed sequential is 2824 KiB / 399.5 requests / 13.84 ms and random
is 2492 KiB / 623 requests / 22.47 ms. Keep the shared 256KiB 16-entry extent
residency cache and exact invalidation.

The combined ID49+ID39 READ path now has its strongest owner result. On the
hwq=64 model sampled lower READ peak reaches 2.0; packed sequential is 2828 KiB
/ 405 requests / 4.59 ms and random is 2472 KiB / 618 requests / 5.11 ms. The
report verdict is FASTER and random p99 now beats both raw 6.08 ms and the
qualified `89fe711...` 5.22 ms baseline. ID39 nevertheless stays Class 4
because this run still does not isolate parallel service from the shared cache.
A default-on `parallel_reads` module parameter provides that same-cache A/B.

ID48 remains closed: sampled singleton tails were a real cause, because ID50
removed exactly that bucket. The result also refutes the stronger claim that
those tails explained all async request inflation: fast async still issues
131.5 more lower WRITE requests than sync.

ID12 remains closed as a snapshot optimization. Pause-side snapshot CRC is
about 1.7 ms slow / 1.1 ms fast and full transaction hashing stays unchanged.
Further residual attribution is optional evidence collection only.

WRITE evidence remains directional. Slow mixed sync/async are both 7.05 MB/s
with 544.0/545.5 lower requests. Fast write-only QD8 is +9.0% async/sync, QD1
+4.8%, QD4 -0.8% and QD32 +0.1%; every point is still one matched pair, so >=5
counterbalanced pairs remain mandatory before K=1 scheduling promotion. Live
GC, suspend/resume and fail-closed fault qualification remain green.

## Current bottleneck ranking

These overlapping wall counters are diagnostic, not additive. In the latest
mixed run lower WRITE remains the largest measured WRITE-path wall at about
603.5 ms slow / 185.9 ms fast. LZ4 preparation is 141.7/79.8 ms and commit
non-I/O is 54.6/37.3 ms. Snapshot pause CRC remains only 1.7/1.1 ms; planner and
explicit copy costs are secondary.

READ amplification is no longer the active defect. The shared extent cache is
qualified independently and the combined fast path reaches depth two with
lower traffic plus FASTER packed reads. The unresolved READ question is only
whether Kread itself adds value once ID49 is held fixed.

WRITE fragmentation is now narrower. ID50 removed all sampled-tail one-page
PACK_READY closes and cut the fast async/sync request excess by about 20%, but
952.5 async requests still exceed 821 sync and deferred singleton deadlines
increased. ID51 measures where those deferred records terminate before another
retention rule is attempted.

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
| 39 | Latency-first bounded parallel READ service | **4 isolated A/B required** | Combined ID49+Kread now reaches peak depth 2.0 with 2828/2472 KiB, 405/618 requests and 4.59/5.11 ms seq/random p99 on the fast model, earning FASTER. Keep ID49 fixed and compare `parallel_reads=0/1` before attributing the win to Kread itself. |
| 40 | Freeze first, then start LZ4/CRC | **5** | Rejected; compression belongs during collection. |
| 41 | Per-lane isolated write accumulators / 2xN packing queues | **5** | Reject by default; destroys global packing view and risks request inflation. |
| 42 | Explicit serial-vs-parallel lower queue model + lower in-flight-depth telemetry | **1 completed measurement** | Owner-qualified. Slow hwq=1 stays at sampled peak depth 1; fast raw reaches >1 while swapz remains at 1. Keep the geometry and telemetry as mandatory evidence for concurrency claims. |
| 43 | Huge/compound-page RAM input support (folio/THP/hugetlb), not only 4KiB page inputs | **4 evidence/coverage** | bio_for_each_segment() already page-normalizes multi-page bvecs; current copies are page-local and page-aligned 4KiB folio slices can direct-map. Do not add nth_page() to iterator bvecs. Add explicit THP/folio coverage; larger base PAGE_SIZE/native larger records remain architecture work. |
| 44 | Exact per-segment authoritative mapping counts / GC map-scan elimination | **1** | Owner-qualified with 20 live victims/rotations and byte-exact 4096-page verification. Keep O(1) dead-segment/post-evacuation checks; victim scoring/evacuation reverse indexing remains a separate future optimization. |
| 45 | 4-block extent payload block-residency cache | **1** | Owner-qualified; keep. Slow packed sequential p99 improved to 16.85 ms with 3056 KiB / 457.5 lower requests, and native C proves each block of a seven-record 16KiB extent is fetched at most once before invalidation. |
| 46 | Timed-interval scheduling telemetry hygiene | **1 completed measurement** | Qualified. Mixed/write-only scheduling conclusions now use kernel snapshots strictly around measured waves; full-process prefill/warmup counters are not evidence. |
| 47 | Explicit ordering-boundary singleton reset | **1** | Qualified correctness/measurement hygiene. PREFLUSH/FUA/discard/shutdown/other reset learned singleton state, including empty fsync PREFLUSH; ordinary idle/deadline closes do not. |
| 48 | Fast mixed one-page PACK_READY cause attribution | **1 completed measurement** | Repaired-read confirmation is 78.0 tail-target / 24.2 read-bypass / 0 wave-interruption, with slow 0/0/0. Sampled singleton tails remain dominant; read-bypass/wave as the primary root cause is refuted. |
| 49 | 16-entry shared multi-extent READ residency cache | **1** | Reconfirmed independently on hwq=1: 2824 KiB / 399.5 requests / 13.84 ms sequential and 2492 KiB / 623 requests / 22.47 ms random. Keep the 256KiB ordered-owner cache and exact invalidation. |
| 50 | Sampled-single-tail PACK_READY deferral | **4 mechanism validated; policy pending repeated evidence** | Fast sampled-tail win1 closes fell 78.0->0.0 without migration to read-bypass (24.2->24.0); async requests fell 1005.5->952.5, but async/sync throughput ratio stayed ~97.1% and one-page deadline closes reached 53.2. Keep the experiment pending ID51 plus >=5 matched pairs. |
| 51 | Deferred-singleton outcome attribution | **4 instrumentation implemented pending owner evidence** | Every ID50 deferral is counted exactly once and must resolve to companion, one-page deadline, one-page idle or other clear. Timed intervals enforce conservation; use this before any second singleton/deadline policy. |


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

1. Owner-qualify ID51 on the unchanged ID50 policy. The timed console must show
   deferred tail D/C/DL/I/O and exact conservation. Determine how much of the
   suppressed ~78 singleton population joins companions versus expires as
   deadline/idle/other work before changing retention again.
2. Use the default-on `parallel_reads` control for an isolated same-cache ID39
   A/B on the fast model. Promote Kread only if depth/latency improve without
   lower-byte/request inflation; ID49 remains Class 1 either way.
3. Run >=5 counterbalanced fast write-only QD8 pairs plus QD1 and mixed-QD32
   controls before promoting/deleting K=1 WRITE scheduling or ID50.
4. Collect trustworthy kernel-worker on-CPU attribution before N=2 preparation
   workers or CPU-topology changes; keep K>1 lower-WRITE slots rejected.
5. Optional: split remaining commit residual only if attribution remains useful;
   do not alter full transaction snapshot hashing.
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
