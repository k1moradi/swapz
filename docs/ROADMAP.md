# Roadmap

**Immutable naming policy (read before every prompt):** The project is `swapz`; the kernel module is `dm-swapz.ko` (loaded as `dm_swapz`); the Device Mapper target is exactly `swapz`; and the module alias is `dm-swapz`. Never put implementation-generation numbers in product, module, target, source-path, report, workflow, helper, or schema names. `SWZ3` is reserved for the on-disk format identity.

**Single official test command (read before every prompt):** Run `make test` at the repository root for every supported swapz test and benchmark. A complete run must report BLOCKED (nonzero) if safe noninteractive privileged qualification cannot run. Do not create, publish, recommend, or document alternative test commands. Private scripts and CI jobs are implementation details, not operator interfaces.

This file contains only active work. Completed experiments and detailed historical transcripts belong in Git history.

## Current baseline

Owner qualification of source
`2fabd0dc4b3fe09b8e52e9a624e9452647229e09` passed all five stages and
published report-only commit
`92d6aa08b44ab7dd827636680584f8c9a313a89b`. Evidence remains newly-created,
positively owned RAM-backed `null_blk` only.

The latest owner run preserves ID63's request benefit but shows its fast-latency
question is not closed. SSD_EMULATED sequential requests improved 403.0 ->
322.6 (-20.0%, paired 95% CI [-24.4%,-15.5%]) while p99 regressed 5.13 ->
5.60 ms (+9.5%, CI [+1.7%,+17.4%]). Serial ID63 improved 399.4 -> 235.2
requests (-41.1%) and 14.32 -> 8.89 ms p99 (-37.8%) with decisive intervals.
The next source removes cache-copy work from rejected pairs and puts shared-LRU
absorption after successful BIO completion; it does not disable ID63 by queue
depth.

ID66 is qualified. The discard epoch/count sidecars are gone; the serialized
precheck temporarily decrements and exactly restores live refs before commit.
The full owner run preserved loaded GC/TRIM, suspend/resume and fail-closed
fault-injection evidence.

ID64 is retired. Completion-aware zero-tail sampling removed the triggering condition; the latest five matched owner rounds observed zero after-I0 shrinks and zero guard skips.

The prior fast write-only QD8 +8.1% paired result used the retired per-QD wave
dispatcher. Keep it only as historical burst evidence; it no longer qualifies
sustained-QD throughput. The corrected persistent-worker sweep must be
owner-qualified before using write-only throughput to promote K=1 scheduling.
Fast mixed remains inconclusive at +4.9%, CI [-0.3%,+10.2%]. ID38 remains on
hold.

ID60 standalone same-extent slot grouping is retired. Ordinary `swapz_read()`
already receives the shared metadata/extent-cache benefit without private-slot
prime/absorb copies. Current source keeps slot execution only for an exact ID63
adjacent coalescing candidate.

Physical endurance and real-device behavior remain unproven.

## Current bottleneck ranking

The immediate read-path work is cleanup, not another performance search:
reject non-ID63 pairs before slot preparation/priming and remove the now-dead
ID39/ID60 directional benchmark sessions. Fast and serial ID63 retain five
matched rounds because they remain promoted request-efficiency mechanisms.

The highest-value new compression question is ID67, but it starts as offline
native-C evidence only. The existing synthetic fixture intentionally contains
cryptographic-noise regions and only 128 repeated payloads, so it is a useful
negative/control corpus rather than representative evidence for predictive
compression. ID67 now maintains only delta64 across scalar/SIMD backends on deterministic
structured binary/numeric archetypes and pass resulting lengths through the
real bounded planner before any SWZ3 format or hot-path change.

ID61 remains an evidence problem: timed mixed I/O observed zero GC victims, so
background GC is unjustified. First measure useful-I/O wall/p99 while foreground
GC is forced under bounded RAM-backed capacity pressure and quantify the current
full-map scan cost at realistic logical-page counts.

ID43 compound/folio coverage and ID36 low-RAM/heavy-CPU qualification remain
independent release work. ID62 physical-media admission remains a separately
authorized safety/deployment gate and is not the next implementation task.

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
| 14 | Extra preparation credits in current synchronous geometry | **5** | Serial lower-WRITE preparation backlog is still 0.00/0.00; fast is only 0.18/0.06. Generic extra credits cannot manufacture enough eligible work. The current candidate instead suppresses idle preparation wakes below four true tails while preserving any-depth lower-WRITE overlap. |
| 15 | >=5 counterbalanced pairs for promoted performance questions | **1 evidence gate implemented** | Retain five matched fast mixed, corrected persistent-worker fast QD8/QD32 and promoted ID63 confirmations where inference still matters; legacy wave-driver write evidence is historical burst evidence only. |
| 16 | N=2/4 preparation workers in old single-credit design | **5** | Refuted as formulated. |
| 17 | Pointer handoff solely to remove current copies | **5** | Reconfirmed: explicit copies are only ~5.1 ms slow / 3.5 ms fast. |
| 18 | Rewrite bounded DP planner | **5** | Reconfirmed: planner is ~6.3 ms slow / 4.4 ms fast and is not dominant. |
| 19 | Skip final publish payload CRC | **5** | Rejected despite measured cost; final immutable-run integrity boundary is mandatory. |
| 20 | Remove batch pause/resume transaction CRC immediately | **5** | No isolated evidence justifies weakening snapshot protection. |
| 21 | Direct LZ4 decompression into read BIO | **5** | Reconfirmed: read-copy wall is ~1.1-1.4 ms while lower READ wall is ~100-675 ms. |
| 22 | DMA/hardware offload for current 4KiB copies | **5** | Wrong bottleneck. |
| 23 | Per-CPU independent authorities on one shared device | **5** | Reject; fragments ordering, GC and global packing. |
| 24 | Trustworthy kernel-worker on-CPU attribution | **2 boundary metric insufficient; phase floors retained** | Latest fast prep is 52.2 ms callback wall / 2.2 ms scheduler delta / 36.8 ms measured non-sleeping floor; ordered is 960.4 / 277.6 / 88.3 ms. Keep boundary deltas only as lower bounds and require external scheduler accounting before N=2/affinity decisions. |
| 25 | Async lower-I/O state machine with immutable run ownership | **1** | Owner-loaded qualification reconfirms the ownership/publication machinery. Keep the infrastructure; K=1 scheduling policy remains separate. |
| 26 | NUMA-local preparation domains | **6** | Hardware-blocked. |
| 27 | One swapz target per NUMA node with node-local backing | **6** | Deployment topology only. |
| 28 | Sustained live-GC workload | **1** | Reconfirmed with exact mapping counts active: 20 victims/rotations, 20 distinct victims and 4096 verified pages. |
| 29 | Dead-segment DISCARD/TRIM | **1 qualified on owned RAM** | Owner evidence confirms 36 exact 1MiB discards / 73728 sectors, 20 GC victims/rotations and byte-exact 4096-page verification. Keep advisory fail-closed semantics; physical endurance remains unproven. |
| 30 | Tiny microsecond grace timer | **5** | Refuted and deleted. |
| 31 | Shared descriptor queue + multiple unbound prep workers | **4 dependent** | Serial still has no preparation backlog and fast remains shallow (~0.21/0.06 at lower-WRITE boundaries). Consider N=2 only after repeated corrected sustained-QD evidence plus trustworthy on-CPU attribution. |
| 32 | One affinity-pinned worker per physical core | **3** | Reject affinity form. |
| 33 | Linux kernel CRC32C primitive | **1** | Already implemented; keep architecture-selected kernel backend. |
| 34 | Hand-selected SIMD/instructions beyond kernel/LZ4 | **6** | CRC is measurable, but verify active backend/on-CPU cost before bypassing kernel primitives. |
| 35 | Firmware/device/upper/lower compute offload | **6** | Hardware/interface dependent. |
| 36 | Heavy-CPU plus low-RAM qualification | **6** | Mandatory before multi-worker/pipeline promotion. |
| 37 | K=1 ping-pong WRITE pipeline | **4 shallow-detach candidate implemented / owner requalification pending** | Owner evidence proves deep sustained gains (+16.3% QD8, +34.6% QD32) but fast QD4 regresses -6.9% and fast mixed adds requests without throughput gain. Detach only when count>4 or confirmed preparation backlog exists; fast QD4/QD8/QD32 now use five matched pairs. |
| 38 | Shared accumulator with K>1 lower-write slots | **5 current opportunity too small** | Fast mixed measures 29.6 ready windows / 87.1 records / 3.58 ms total K=1 completion wait. Keep passive counters; do not add K=2 authority state. |
| 39 | Latency-first bounded parallel READ service | **5 refuted; helper removed from current source** | Owner evidence showed no standalone benefit. ID65 removes the `swapz-read` helper; the legacy `parallel_reads_enabled`/read-worker CPU status tokens remain zero for schema compatibility. |
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
| 50 | Sampled-single-tail PACK_READY deferral | **1 qualified / keep** | Latest fast D/C/DL/I/O is 110.8/78.3/32.5/0/0; only 2.0 companions resolve after 1 ms. Keep the ordinary deadline; do not add another active age cutoff. |
| 51 | Deferred-singleton outcome attribution | **1 completed measurement** | Reconfirmed fast D/C/DL/I/O = 98.8/65.8/33.0/0/0 with exact conservation. Retain counters while residual fragmentation is localized. |
| 52 | Deferred-singleton timing/service discrimination | **1 completed measurement** | Full-deadline passive data returns to only 1.5/65.8 companions >1 ms. Together with ID53's feedback artifact, this closes the age-threshold path: retain diagnostics only; do not implement another cutoff. |
| 53 | 1 ms deferred-singleton age cutoff | **5 refuted / reverted** | 31.5 cutoff closes produced 13.8 next-WRITE-before-original-deadline observations (43.8%). Fast mixed async also had 960.4 vs 822.6 sync lower requests and no confirmed >=5% gain. Remove the active cutoff and watermark; restore ID50's ordinary deadline. |
| 54 | Passive PACK_READY primary-cause attribution | **1 completed measurement** | Latest fast evidence: tail -41.2 CI [-71.1,-11.3], burst +90.2 [+36.9,+143.5], service-dry +30.4 [+3.5,+57.3]. Small-tail suppression remains refuted; dry is now a secondary fragmentation signal. |
| 55 | Learned burst-target PACK_READY site/geometry attribution | **1 completed measurement** | All burst closes remain admission-side (24.6/114.8 sync/async; worker 0/0). count17-64 is +66.2 CI [+26.4,+106.0] and overshoot +71.4 [+27.5,+115.3]. Do not gate only small targets or worker-tail closure. |
| 56 | Post-PACK tail-sample timing vs detached K=1 state | **1 completed measurement** | Fast async records 604.2 tail0/inflight vs 0 sync, plus 116.4 tail1/inflight and 70.4 tail2+/inflight. The timing asymmetry is proven, but slow async also has many tail0/inflight samples without a throughput loss, so use a controlled active successor rather than declaring causality. |
| 57 | K=1-busy PACK_READY gate + completion-aware zero-tail preservation | **3 refuted by owner evidence; reverted** | Two qualified runs reproduce ~-42% fast-QD8 async/sync. Latest is -41.1%, CI [-45.8%,-36.4%], with QD8 target 12 and 274.8 deadlines; fast mixed adds +271.6 lower requests while service-dry closes rise +263.4. Restore ID56/pre-ID57 sampling/closure behavior and remove active ID57 counters. |
| 58 | Nonzero same-filled-page special representation | **4 low-priority representative-corpus evidence** | Current synthetic trace has 0/12,301 nonzero same-filled writes and 0 final live same-filled pages, so there is no benchmark opportunity. Keep the offline detector; do not add a production representation until representative swap content shows prevalence. |
| 59 | Exact-content page deduplication / shared payload ownership | **4 representative-corpus + architecture evidence** | Synthetic trace reports 12,301 resident duplicate opportunities from only 128 payloads and 1,024 final duplicate pages. This proves the analyzer, not production prevalence. Measure representative lifetime overlap before implementing collision-free verification, bounded refcounts, generation-safe COW and GC/DISCARD ownership. |
| 60 | Queued READ grouping within the same immutable extent | **5 refuted / retired** | Five matched hwq=1 rounds showed no request win and an unfavorable p99 direction; the qualified post-ID65 fast directional sample was also worse. Remove standalone slot grouping and its dedicated benchmark controls; ordinary reads keep the shared caches. |
| 61 | Background/asynchronous GC instead of foreground collection stalls | **1 incremental victim accounting owner-qualified; background worker refuted** | The latest owner run reports choose-map=0 and 0.02 ms total victim-choice wall across 20 rotations, with total foreground-GC wall only 0.65% of useful-WRITE wall. Native 4GiB-equivalent selection is 0.014 ms versus 17.475 ms for the old map score scan; relocation remains a separate 4.607 ms full-map scan. Keep foreground GC and no per-page reverse index until loaded scaling proves relocation material. |
| 62 | Real-device / physical-media qualification | **6 safety/deployment gate** | Still blocked. ID29 RAM qualification does not authorize physical storage, active swap, or a bypass module parameter. Real-device work requires separate owner authorization, device-loss acceptance, identity/alias checks, endurance/error metrics and independent safety review. |
| 63 | Physically adjacent distinct-extent READ coalescing | **4 fast-latency repair implemented / owner requalification pending** | Latest owner evidence keeps the request win but exposes fast p99: SSD_EMULATED seq req -20.0% CI [-24.4%,-15.5%] with p99 +9.5% CI [+1.7%,+17.4%]; serial seq req -41.1% and p99 -37.8%. Current source rejects from shared-cache metadata before private cache copies and absorbs shared LRU state after upper BIO completion. |
| 64 | One-shot in-flight-zero burst-target shrink guard | **5 retired** | Completion-aware zero-tail sampling made the trigger disappear: latest five matched rounds report after-I0=0 and skip-I0=0. Remove the branch/module parameter/A-B; retain only fixed-zero compatibility status tokens. |
| 65 | Retire ID39 `swapz-read` helper | **1 owner-qualified / keep** | The helper remains correctly retired and legacy helper status/CPU tokens stay zero. The latest owner run shows a separate ID63 fast-p99 regression even without that helper, so current cleanup targets private cache-copy/completion ordering rather than restoring read concurrency. |
| 66 | Zero-allocation multi-page DISCARD liveness prevalidation | **1 owner-qualified / keep** | Saves 6 bytes/physical 4KiB block (~1.5 MiB/GiB) while preserving all-or-nothing shared-extent liveness validation. Full loaded lifecycle/GC/TRIM/fault evidence passed. |
| 67 | Predictive rescue before LZ4 | **4 ID67a.5 operation-specific SIMD + routed CPU evidence implemented** | The classifier is scalar-only; transform/inverse dispatch independently. Native qualification batch-times available backends and reports routed CPU ns/page and ns/saved-block. SWZ3/data-path integration remains gated. |
| 68 | Placement/reclaim telemetry | **4 implemented / owner qualification pending** | Report foreground/GC alignment-hole blocks, adjacent-run splits caused by holes, allocator probe segments/full scans/wall time, duplicate successful-DISCARD skips and logical segment-open distribution. Evidence only; no SWZ3 or planner-policy change. |
| 69 | Hole-free 4KiB-aligned extent placement | **4 evidence-gated A/B** | Keep current 1/2/4-block SWZ3 extent classes. Implement only as a temporary matched A/B if ID68 proves material holes; accept only with zero holes, no request/GC regression and neutral-or-better throughput. |
| 70 | Segment DISCARD lifecycle | **3 duplicate suppression implemented / early async TRIM deferred** | Remember successful whole-segment DISCARD and skip the same dead bytes on reuse; any later synchronous or K=1 async WRITE clears that state before submission. Early background TRIM needs a separate ownership/race design and evidence. |
| 71 | Dead-segment allocation probe scaling | **3 mapped-count fast reject implemented / owner qualification pending** | Reject nonzero `segment_mapped_pages` before the 256-block scan; retain the complete physical liveness scan for the zero-mapped reuse candidate. Native evidence compares old/new near-full allocation at 1GiB/4GiB-equivalent scales. |
| 72 | Wear-aware free-segment choice / cold relocation | **6 physical-media evidence gate** | Logical segment-open counts are allocator distribution telemetry, not NAND wear. Do not add wear leveling or cold relocation from RAM-backed evidence alone. |
| 73 | Flexible/larger extent study | **4 offline evidence next** | Compare current aligned 1/2/4, hole-free 1/2/4, exact block-count classes and larger 32/64/128KiB candidates separately from shared multi-page compression. No SWZ3 change without a Pareto win. |


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

## Deferred content/concurrency evidence backlog

The current turn is evidence-only: no scheduling, storage-format or I/O-policy
behavior changes. ID63 stays enabled; ID38 remains passive.

- **ID38:** retain ready-wait windows/records/wall/cause; do not implement K=2.
- **ID65:** owner-qualify the synchronous read-path cleanup; do not restore or
  replace the rejected helper workqueue unless new measured evidence requires it.
- **ID58/59:** keep representative-content collection offline.
- **ID61:** add foreground-GC stall/reserve-headroom evidence under bounded useful pressure.
- **ID62:** physical devices remain outside the current development safety scope.

## Immediate work queue

1. Owner-qualify ID68, ID70 duplicate-DISCARD suppression and ID71 with the
   existing full `make test` matrix. Use the new placement/probe/TRIM/program
   telemetry to decide the next allocator experiment; do not change SWZ3.
2. If ID68 reports material alignment holes, run ID69 as a matched temporary
   A/B using the existing 1/2/4-block extent classes and 4KiB physical
   alignment. Keep only a Pareto-neutral-or-better result.
3. Build ID73 as an offline extent-geometry/compression-granularity study
   before widening SWZ3 classes, masks, caches or scratch buffers.
4. Keep the qualified shallow K=1 detach baseline unchanged. Keep K>1 writes,
   background GC, a reverse index and early asynchronous TRIM deferred until
   fresh evidence demonstrates a material blocked-work or lifecycle benefit.
5. Continue representative ID67 content/CPU evidence and the bounded ID63
   fast-latency A/B independently of allocator work.
6. Keep ID62 blocked until RAM-backed kernel/format evidence is settled and
   physical-device testing is separately authorized.

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
