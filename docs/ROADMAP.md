# Roadmap

**Immutable naming policy (read before every prompt):** The project is `swapz`; the kernel module is `dm-swapz.ko` (loaded as `dm_swapz`); the Device Mapper target is exactly `swapz`; and the module alias is `dm-swapz`. Never put implementation-generation numbers in product, module, target, source-path, report, workflow, helper, or schema names. `SWZ3` is reserved for the on-disk format identity.

**Single official test command (read before every prompt):** Run `make test` at the repository root for every supported swapz test and benchmark. A complete run must report BLOCKED (nonzero) if safe noninteractive privileged qualification cannot run. Do not create, publish, recommend, or document alternative test commands. Private scripts and CI jobs are implementation details, not operator interfaces.

This file contains only active work. Completed experiments and detailed historical transcripts belong in Git history.

## Current baseline

Owner qualification of source
`64852c6e1b229a8940eea434d20c440fe434406c` passed all five stages and
published report-only commit `617ab932331d9b44e66f8f839fd1f7975bc545af`.
Evidence remains newly-created owned-RAM `null_blk` only.

ID37 K=1 async preparation remains useful at fast write-only QD8 in the latest
run: 23.00 versus 20.99 MB/s, +9.7% paired with 95% CI [+1.4%,+18.0%].
The exact target remains 8 with 512 PACK_READY and zero deadline closes in the
five-pair QD8 confirmation. ID38 remains too small for K>1: fast mixed records
29.6 ready windows / 87.1 records / 3.58 ms total K=1 completion wait.

ID60 is now refuted as a standalone performance optimization. On the serial
hwq=1 model with ID63 disabled, grouping changes sequential lower READ requests
398.0 -> 397.0 (-0.2%, CI [-1.7%,+1.3%]) and p99 13.24 -> 14.00 ms
(+5.7%, CI [-1.5%,+13.0%]). Keep only a directional regression control.

ID63 is strongly qualified. Fast isolated five-pair evidence reduces
sequential lower READ requests 404.6 -> 343.6, -15.0% with 95% CI
[-19.3%,-10.8%], with zero extra blocks. Serial-depth isolation reduces
398.4 -> 248.2, -37.7% with CI [-46.1%,-29.2%]. Of the fast 163.8 adjacent
sequential pairs, 63.8 merge, 98.4 are already cache-satisfied, only 1.6 have
an exact-range gap, and noncontiguous/other are zero. The exact zero-padding
rule therefore already captures nearly all useful uncached adjacency; do not
broaden it with padding or hole filling.

Fast mixed attribution now isolates the scheduling defect targeted by ID64.
Async averages 8.2 learned-target shrinks: 7.6 (92.7%) happen after an
in-flight zero-tail sample, zero follow read bypass, and only 0.6 are other.
All 7.6 after-I0 cases shrink to <=8. Sync has zero after-I0 shrinks. This is
strong mechanism evidence, but the new guard still requires its own matched
performance A/B before promotion.

ID39 helper concurrency remains unhelpful: the owner-qualified fast A/B with
ID63 disabled showed sequential requests 404.2 -> 407.2 and p99 +0.7%,
CI [-13.1%,+14.5%], with random p99 also inconclusive. Keep the workqueue
unchanged during ID64 qualification; treat removal as a later simplification.

ID29 lifecycle evidence remains qualified on owned RAM: 20 victims/rotations,
20 distinct victims at 1/1 min/max, 4096 verified pages and 36 exact 1MiB
DISCARDs (73728 sectors). Physical endurance remains unproven.

## Current bottleneck ranking

The highest-value active question is now ID64, not broader READ merging or more
WRITE slots. ID63 has already eliminated the useful adjacent READ requests it
can remove without amplification, and ID38 exposes only 3.58 ms of K=1 ready
wait in fast mixed.

ID64 asks a deliberately narrow question: when the post-PACK sampler observed
`tail == 0` while K=1 was still active, should exactly the next would-be
learned burst-target shrink be ignored? The experiment must not suppress
PACK_READY, defer sampling, hold BIO completions, or alter lower-run ownership.

The observation must be one-shot. A guarded shrink candidate consumes it
immediately; otherwise the first nonempty non-chaining hard boundary consumes
it. This prevents a stale flag from suppressing genuine later down-adaptation
after the workload actually falls to lower queue depth.

Qualification keeps async preparation enabled in both ID64 arms and varies
only the read-only guard control for five counterbalanced fast mixed rounds.
Already-refuted ID39 and ID60 experiments are retained only as directional
regression controls to avoid repeating expensive evidence collection on every
official `make test`. Both fast and slow ID63 five-pair confirmations remain.

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
| 15 | >=5 counterbalanced pairs for mixed/QD points | **1 evidence gate implemented** | The owner run produced five matched fast mixed, fast QD8 and Kread comparisons. Keep the harness; only fast write-only QD8 has a CI excluding zero in the useful direction. |
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
| 31 | Shared descriptor queue + multiple unbound prep workers | **4 dependent** | Serial still has no preparation backlog and fast remains shallow (~0.21/0.06 at lower-WRITE boundaries). Consider N=2 only after repeated fast-QD8 evidence plus trustworthy on-CPU attribution. |
| 32 | One affinity-pinned worker per physical core | **3** | Reject affinity form. |
| 33 | Linux kernel CRC32C primitive | **1** | Already implemented; keep architecture-selected kernel backend. |
| 34 | Hand-selected SIMD/instructions beyond kernel/LZ4 | **6** | CRC is measurable, but verify active backend/on-CPU cost before bypassing kernel primitives. |
| 35 | Firmware/device/upper/lower compute offload | **6** | Hardware/interface dependent. |
| 36 | Heavy-CPU plus low-RAM qualification | **6** | Mandatory before multi-worker/pipeline promotion. |
| 37 | K=1 ping-pong WRITE pipeline | **1 qualified at fast write-only QD8** | Latest owner run: +9.7%, CI [+1.4%,+18.0%], exact target 8 and 512/0/0 PACK_READY/deadline/idle. Mixed remains a separate scheduling problem; keep K=1 and do not add slots. |
| 38 | Shared accumulator with K>1 lower-write slots | **5 current opportunity too small** | Fast mixed measures 29.6 ready windows / 87.1 records / 3.58 ms total K=1 completion wait. Keep passive counters; do not add K=2 authority state. |
| 39 | Latency-first bounded parallel READ service | **5 performance refuted; cleanup pending** | Owner-qualified fast A/B with ID63 off: seq requests 404.2 -> 407.2, seq p99 +0.7% CI [-13.1%,+14.5%], random p99 -5.0% [-18.5%,+8.6%]. Keep one directional regression control and defer workqueue removal until after ID64. |
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
| 60 | Queued READ grouping within the same immutable extent | **5 standalone benefit refuted** | Five matched hwq=1 rounds with ID63 off show seq req -0.2% CI [-1.7%,+1.3%], seq p99 +5.7% [-1.5%,+13.0%], random flat. Keep only a directional control; do not build a separate grouping optimization. |
| 61 | Background/asynchronous GC instead of foreground collection stalls | **4 dependent evidence** | Lifecycle GC is correct (20 victims/rotations), but timed mixed reports no foreground GC victims. First measure foreground GC stall/headroom during useful pressure; a worker is unjustified until GC materially contributes to latency with reserve headroom. |
| 62 | Real-device / physical-media qualification | **6 safety/deployment gate** | Still blocked. ID29 RAM qualification does not authorize physical storage, active swap, or a bypass module parameter. Real-device work requires separate owner authorization, device-loss acceptance, identity/alias checks, endurance/error metrics and independent safety review. |
| 63 | Physically adjacent distinct-extent READ coalescing | **1 qualified fast + serial request win** | Fast seq req -15.0% CI [-19.3%,-10.8%]; serial seq req -37.7% [-46.1%,-29.2%], zero extra blocks. Unmerged adjacency is overwhelmingly cache-satisfied; noncontiguous is zero and exact-range gaps are tiny. Keep the exact zero-padding design. |
| 64 | One-shot in-flight-zero burst-target shrink guard | **4 active bounded experiment** | Fast async attribution shows 7.6/8.2 shrinks follow in-flight zero-tail sampling and all 7.6 collapse the target to <=8. Guard only the next real shrink candidate, consume the flag once, and run five matched fast async guard-off/on rounds before promotion. |


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
- **ID39:** retain the read workqueue until the new depth-one A/Bs partition the
  read win; do not remove or expand it in the attribution commit.
- **ID58/59:** keep representative-content collection offline.
- **ID61:** add foreground-GC stall/reserve-headroom evidence under bounded useful pressure.
- **ID62:** physical devices remain outside the current development safety scope.

## Immediate work queue

1. Owner-qualify ID64 with five matched SSD_EMULATED QD32 mixed rounds:
   async preparation on in both arms, vary only
   `guard_inflight_zero_shrink=0/1`. Require guard-off skip count zero,
   guard-on positive skip count, and guard-on actual `after-I0` shrinks zero.
   Report paired CIs for write throughput, lower WRITE requests, read/write
   p99, burst closes, overshoot and actual shrink count.
2. Preserve one-shot behavior: a guarded candidate consumes the flag, and the
   first nonempty non-chaining hard boundary clears any unconsumed flag. Do not
   reintroduce ID57 PACK_READY suppression or tail-sample deferral.
3. Keep fast/slow ID63 five-pair confirmation. Keep ID39 and slow ID60 only as
   one off/on directional controls because their five-pair performance
   questions are already owner-qualified.
4. If ID64 wins without QD8/read regressions, promote it and then consider
   removing the unhelpful ID39 helper workqueue in a separate cleanup.
5. Continue ID43 compound/folio coverage and ID61 useful-I/O GC-pressure
   evidence independently. ID62 physical-media work remains separately
   authorized and must not weaken null_blk-only admission.

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
