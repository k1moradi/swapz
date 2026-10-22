# Roadmap

**Immutable naming policy (read before every prompt):** The project is `swapz`; the kernel module is `dm-swapz.ko` (loaded as `dm_swapz`); the Device Mapper target is exactly `swapz`; and the module alias is `dm-swapz`. Never put implementation-generation numbers in product, module, target, source-path, report, workflow, helper, or schema names. `SWZ` is the current unversioned on-disk format identity; do not assign a format version until an incompatible format boundary is justified.

**Single official test command (read before every prompt):** Run `make test` at the repository root for every supported swapz test and benchmark. A complete run must report BLOCKED (nonzero) if safe noninteractive privileged qualification cannot run. Do not create, publish, recommend, or document alternative test commands. Private scripts and CI jobs are implementation details, not operator interfaces.

This file contains only active work. Completed experiments and detailed historical transcripts belong in Git history.

## Current baseline

The latest successful standard owner matrix tested source
`5bf2c0a6f0384ccf3829dc02dc0e9b737c857e40`, passed all five stages, and
published report-only commit
`85aeac4cbb368bb4900cd94c9c73f46d952520ef`. This qualifies alpha.26's
metadata-key deduplication, final producer drain and aligned preparation array
on owned RAM-backed `null_blk`.

The later owner run of `b7aae67fc230ceb4323e8be4c6f1ebf219cba405` failed in
stage 2 before loaded benchmarking because the native source-contract helper
did not recognize alpha.27's `swapz_u16` metadata-cache helper return type.
Report-only commit `7faef62418e9563efde947cef432e63af1236629` records that
FAIL with the loaded matrix `NOT_RUN`. Commits
`55183d7c7d041c74068ed553ba42213fc44cf713` and
`30ba10ce38ebae3da2e401bba15b1ca4178765c5` repair and pin only that test
parser behavior; alpha.27 and subsequent current-main changes still require a
complete owner `make test` before they become the qualified baseline.

Against the preceding `9a802eff` report, fast random backing reads fell from
3592 to 2993 KiB and 734.6 to 678 requests. Directory hit rate rose from 71.2%
to 86.8%; random replacements fell from 309.4 to 134.4, sequential from 441 to
43. These cross-run observations support the duplicate-key repair, while the
remaining I/O difference from the older `5bdd040` baseline motivates a bounded
two-choice cache experiment. Host load and post-write geometry prevent a clean
causal attribution of the entire remaining difference to set conflicts.

Five matched fast-model async/sync write pairs measured QD4 -0.4% (95% CI
[-4.4%,+3.6%]), QD8 +28.7% ([+21.9%,+35.5%]), and QD32 +27.1%
([+21.8%,+32.5%]). QD8 requests fell 23.7% and bytes rose 0.55%; QD32
requests rose 17.7% and bytes 0.72%; all four intervals exclude zero.
Fast mixed throughput +3.2% ([-1.9%,+8.4%]) is inconclusive versus sync.
Rescue remains off with zero classifier/transform activity.

Fast QD32 whole-host CPU activity averaged 42.2% sync versus 55.0% async;
CPU PSI averaged 20.5% versus 27.0%. These include benchmark, kernel and
background work such as Codex. They do not isolate swapz CPU or establish an
idle-host control. Low-RAM/heavy-CPU, sustained churn, real kernel swap and
physical-media qualification remain open. Steps 1/2 have their standard RAM
qualification; Steps 3/4/5 (asynchronous TRIM, churn/WAF, map compaction) remain
outstanding. Alpha.27 is one reviewed cache follow-up before Step 3.

## Current bottleneck ranking

The next owner run must qualify alpha.27's two-choice metadata directory.
The hypothesis is fewer distinct-key conflict evictions at fixed 512-slot RAM,
with one-line primary hits and an eight-tag worst case. Keep write scheduling,
K=1, delta64 and extent geometry fixed. Require exact readback and lifecycle
success, and compare lower READ bytes/requests, primary/secondary hits,
replacements, engine wall time, throughput/p99 and CPU/load context. No local
compilation or tests were run. After this isolated cycle, return to Step 3's
early asynchronous TRIM design review; no further pipeline policy is promoted.
ID36 resource-pressure qualification remains a separate release requirement.

Ordinary benchmark reports now observe host CPU activity and PSI at phase
boundaries. These observations expose contention but do not supply an idle
control or qualify deliberate resource pressure. Keep Codex-active and earlier
idle-host evidence distinct when drawing performance conclusions.

Next, attribute QD32 request inflation using the existing matched per-session
burst target, window bins, PACK_READY causes and producer counters. A correlation
is a hypothesis for one controlled experiment, not permission to discard the
measured deep-QD throughput gain. Retain the current K=1 activation thresholds.

Realistic churn/GC/TRIM evidence follows: about 70% logical occupancy, an explicit
cold/hot split, and at least ten logical capacities of hot rewrites. Verify all
live pages, report foreground plus GC write amplification, victim live ratios,
TRIM wall/latency, useful throughput/p99 and segment-open distribution. A run
with zero GC victims cannot qualify GC amplification or stall behavior; specify
and report placement/capacity pressure that actually exercises live victims.
Only then decide whether asynchronous TRIM merits the added state machine.
Fast and serial adjacent READ coalescing retain five matched rounds.

ID67 remains an opt-in production page-local rescue path. Raw LZ4 remains the first
attempt. RAW or >2024-byte baselines use the scalar 8->32-pair classifier
at threshold 24; smaller LZ4 packing candidates use threshold 16 and must
cross their exact uniform packing limit before adoption. A selected page is transformed with the
runtime SIMD/scalar delta64 backend, compressed a second time, and adopted only
when the stored payload is strictly smaller than the raw-LZ4 baseline. SWZ
records carry the encoding explicitly and reads invert delta64 after LZ4.
Transforms never span logical pages or packed extents, preserving independent
authority, selective reads, GC relocation and random-read units. Source
`5bdd040` recorded zero classifier passes on its loaded fixture, but its fixed
first-stage sample phase could miss structured pages behind repeated headers.
That zero-call result does not establish that representative pages lack useful
delta64 structure. The current correction rotates first-stage samples across
all 128-byte lanes and 16-byte phases, adds deterministic classifier controls,
and shares exact eligibility/adoption helpers between production and native
qualification. This correction still needs the owner's exact-source run. Keep
`delta64_rescue=0` until a corrected, representative rescue-on/off loaded A/B
measures actual lower-WRITE bytes/requests, useful throughput, latency and rescue
cost. Disabled targets continue to allocate no predictor scratch and perform
no rescue classification or timing.

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
| 36 | Heavy-CPU plus low-RAM qualification | **6** | Open release gate for the async default and any increase beyond K=1. Measure target-creation behavior and resource use under memory pressure and CPU oversubscription before release qualification. |
| 37 | K=1 ping-pong WRITE pipeline | **1 standard owned-RAM matrix passed; release gate open** | Five matched fast sustained-write pairs show async/sync QD4 +0.52% CI [-6.90%,+7.95%], QD8 +30.21% [+26.03%,+34.39%], and QD32 +20.75% [+15.66%,+25.84%]. Keep K=1 and existing activation gates; fast mixed remains inconclusive. |
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
| 61 | Foreground GC scaling / background-GC question | **1 ID61b owner-qualified / keep; broader background-GC question remains open** | Report `85aeac4` proves the production survivor list in loaded GC: 20 relocated pages produced exactly 20 relocation-list visits, `gc_choose_map_entries=0`, 1,280 segment-score visits, 20 victims/rotations and byte-exact verification of all 4,096 pages. The same qualified report's native scaling measured full-map relocation at 1.215/4.901ms versus 0.00169/0.00196ms for the 256-survivor list at 1/4GiB-equivalent scale. Keep the per-segment list; realistic foreground-GC stall/headroom evidence remains separate. |
| 62 | Real-device / physical-media qualification | **6 safety/deployment gate** | Still blocked. ID29 RAM qualification does not authorize physical storage, active swap, or a bypass module parameter. Real-device work requires separate owner authorization, device-loss acceptance, identity/alias checks, endurance/error metrics and independent safety review. |
| 63 | Physically adjacent distinct-extent READ coalescing | **1 owner-qualified / active default-on; exact-current-main rerun pending** | Latest successful report `85aeac4` reconfirms fast sequential lower requests -21.09% CI [-23.64%,-18.54%] while throughput -1.11% CI [-13.53%,+11.31%] and p99 -1.02% CI [-6.26%,+4.21%] both cross zero. Serial sequential requests improve -40.16% [-42.06%,-38.26%], throughput +52.03% [+46.23%,+57.83%], and p99 -36.28% [-43.57%,-28.99%]. Keep `read_coalesce=1` as production policy; rerun after alpha.27 because the READ cache changed after this qualified source. |
| 64 | One-shot in-flight-zero burst-target shrink guard | **5 retired** | Completion-aware zero-tail sampling made the trigger disappear: latest five matched rounds report after-I0=0 and skip-I0=0. Remove the branch/module parameter/A-B; retain only fixed-zero compatibility status tokens. |
| 65 | Retire ID39 `swapz-read` helper | **1 owner-qualified / keep** | The helper remains correctly retired and legacy helper status/CPU tokens stay zero. The latest owner run shows a separate ID63 fast-p99 regression even without that helper, so current cleanup targets private cache-copy/completion ordering rather than restoring read concurrency. |
| 66 | Zero-allocation multi-page DISCARD liveness prevalidation | **1 owner-qualified / keep** | Saves 6 bytes/physical 4KiB block (~1.5 MiB/GiB) while preserving all-or-nothing shared-extent liveness validation. Full loaded lifecycle/GC/TRIM/fault evidence passed. |
| 67 | Page-local delta64 rescue around LZ4 | **4 opt-in evidence; default-off owner-qualified** | Earlier loaded enabled-policy evidence saw eligible traffic in all 14 mixed and 40 sustained-write sessions but zero classifier passes, attempts or adoptions while still charging classifier wall time; that justified making rescue default-off. The current route keeps threshold 24 for RAW/>2024-byte baselines and adds a threshold-16 <=2024-byte path only when delta64 can cross the exact next SWZ packing limit. Keep codec/GC read support; the newer packing-aware route still needs representative content and a controlled loaded rescue-on/off comparison before promotion. |
| 68 | Placement/reclaim telemetry | **1 owner-qualified / tail split added for ID69 evidence** | Report 711ceaad qualified aggregate placement/reclaim telemetry and ID70c. Aggregate hole counters continue to include segment-tail waste for continuity; separate tail-waste counters now let ID69 distinguish avoidable internal gaps from unavoidable segment-edge waste. |
| 69 | Hole-free 4KiB-aligned extent placement | **1 packed placement owner-qualified; aligned policy retired** | Report `013893fa` passed the repaired append-only segment-edge cases and loaded packed placement with 128 byte-exact pages, zero internal holes and zero hole-induced run splits. Aligned placement and its A/B harness remain retired; preserve tail-only waste and zero-split invariants without changing SWZ. |
| 70 | Segment DISCARD lifecycle | **1 ID70a + ID70c owner-qualified / keep** | Report 711ceaad shows 20 completed 1MiB GC TRIMs, 16 duplicate skips, plus one immediate upper-DISCARD TRIM followed by one reuse skip. Early/background async TRIM remains deferred. |
| 71 | Dead-segment allocation probe scaling | **1 owner-qualified / keep** | Report 712b98e0 shows 0.430->0.002ms at 1024 segments and 1.688->0.007ms at 4096 segments; loaded probing scanned 80/2497 candidates fully. Keep the mapped-count fast reject plus full zero-candidate scan. |
| 72 | Physical wear / logical allocator fairness | **4 production switch/native semantics implemented; loaded A/B still missing** | Optional `logical_open_balance=1` prefers the least-opened eligible dead destination and uses logical-open count only as an exact-score/count GC victim tie-break, but the official loaded harness still requires `logical_open_balance=0`. The latest qualified baseline already reports 1/1.25/2 min/mean/max opens across 64 segments and 80 opens, the best possible integer min/max spread for that workload. Keep default-off; any promotion test needs deliberately skewed churn plus allocator-probe/GC/I/O/throughput/tail comparisons. Logical opens are not NAND P/E cycles and cannot support physical-wear claims. |
| 73 | Flexible/larger extent study | **5 larger/irregular classes deprioritized** | Report 711ceaad shows packed 1/2/4 captures the dominant geometry gain. A 3-block class saves only 2/2,089 blocks; 32/64KiB maxima save 14/22 more blocks while cold-read cost rises 1.47->1.53/1.55. Keep SWZ 1/2/4 classes unchanged unless a broader representative corpus materially overturns this result. |


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

The first implementation should **not** silently change SWZ format semantics:
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

The alpha.24 policy change only enables the already implemented bounded
`async_prepare` path by default. Do not change its scheduling gates, K=1
ownership, storage format, or ID63 behavior in this step. ID38 remains passive.

- **ID38:** retain ready-wait windows/records/wall/cause; do not implement K=2.
- **ID65:** owner-qualify the synchronous read-path cleanup; do not restore or
  replace the rejected helper workqueue unless new measured evidence requires it.
- **ID58/59:** keep representative-content collection offline.
- **ID61:** add foreground-GC stall/reserve-headroom evidence under bounded useful pressure.
- **ID62:** physical devices remain outside the current development safety scope.

## Immediate work queue

The reviewed allocation/rescue-gate increment and inherited metadata-locality
work need an exact-source owner run before another kernel experiment. Static
AVX-512 review/build evidence does not qualify runtime on this SSE2-only host.

1. Packed-placement retirement is owner-qualified and remains covered by the
   loaded zero-hole/zero-split invariant.
2. The alpha.24 production-C change enables `async_prepare=1` by default.
   Standard owned-RAM qualification passed on the source and report named
   above. Keep K=1 and its existing activation gates, retain
   `async_prepare=0` as the sync control, and preserve the fast-mixed paired
   intervals. The ID36 low-RAM/heavy-CPU gate still blocks release
   qualification of the default-on path.
3. Implement the low-RAM/heavy-CPU evidence step first. Attribute QD32 requests
   next, then collect realistic churn/GC/TRIM evidence before choosing the
   asynchronous-TRIM implementation. The design below is a review proposal.
4. Keep `logical_open_balance=0` until the churn A/B establishes allocator
   spread and probe/GC cost. Logical opens remain distinct from NAND wear.
5. Keep SWZ 1/2/4 classes, K=1 scheduling and ID63 completion semantics
   unchanged. Do not implement the currently weak 3/8/16-block class ideas.
6. Fully qualify the production ID67 route, including byte-exact delta64 reads,
   GC preservation and fast/slow CPU-throughput effects; first owner-qualify the
   corrected classifier and shared native/production routing, then run a
   representative-content rescue-on/off loaded A/B. Map RAM compaction remains
   an isolated later experiment with measured bytes/page.
7. Keep ID62 blocked. Physical-device testing remains separately unauthorized
   and requires its own owner approval and safety review.

## Deferred asynchronous segment TRIM design for review

Step 3 of the owner's original plan is deferred behind resource-pressure and
churn evidence following the external review of source `1888781`. This is a
proposal for independent review before any kernel implementation. The current
`swapz_discard_dead_segment()` still calls
`blkdev_issue_discard()` synchronously. It runs during allocator reuse, after
GC role rotation, and when upper DISCARD removes a closed segment's last map.
Overwrite-created deaths have no early notification. The latest passing owner
report therefore qualifies the existing synchronous mechanism only.

The proposed implementation is bounded to one outstanding whole-segment TRIM
per target and a preallocated pending bitmap indexed by physical segment.
Authority transitions would record candidates only after successful RAW,
compressed or zero/discard publication has settled all mapping counts and
survivor lists. Notification must not allocate, submit I/O or fail a committed
mapping transition. A GC victim becomes eligible only after its role exchange
commits. Zero maps alone are insufficient: immediately before reservation,
the ordered owner must revalidate all live refs, OPEN/reserve roles, staged
transactions and the immutable lower-WRITE run.

The state transition to review is queued -> reserved -> submitted -> completed
-> reaped. A dedicated reclaim-safe submission context would keep BIO allocation
and block-layer submission off the ordered upper-I/O worker. Completion would
record status and wake the ordered owner; that owner would publish successful
`segment_trimmed` state and retire the reservation. Every allocator path,
including the balancing selector and GC reserve destination, must respect this
reservation. Queued but unsubmitted work may be cancelled for reuse. A submitted
discard cannot be cancelled by clearing a flag or skipping a helper call.

The unresolved design decision is reuse under capacity pressure. If the sole
usable destination has a submitted TRIM, simply skipping that segment can turn
temporary I/O into false ENOSPC, while waiting on the ordered worker can stall
unrelated upper I/O. The preferred review candidate is completion-driven retry
that retains the exact accepted BIO/window ownership and committed prefix,
without repeating successful writes or spinning. A bounded wait at that exact
reuse fence is a simpler alternative that requires an explicit exception to
the plan's no-upper-path-wait requirement. Resolve this choice before coding.

Suspend/destruction must stop new TRIM dispatch, cancel pending candidates,
drain submission and outstanding callbacks, reap completion, and only then free
the target, queues and backing reference. Device TRIM errors remain advisory;
ownership disagreement remains fatal. Failed or unsupported TRIM must not set
`segment_trimmed`. The callback must never publish maps or complete upper BIOs.

The official qualification will need deterministic coverage of overwritten
closed-segment death, same-segment replacement, a delayed discard racing reuse,
the last eligible destination, GC reserve rotation, duplicate suppression,
submission/allocation/device failures, and suspend/destruction with a discard
outstanding. Byte-exact readback and independent lower DISCARD counters are
required. Report death/reuse dispatch counts, maximum discard latency,
submission wall time, deferred-reuse pressure and exact completion accounting.
The normal throughput matrix alone cannot prove this ownership protocol.

The [Linux 7.0 discard helper](https://github.com/torvalds/linux/blob/v7.0/block/blk-lib.c)
builds chained BIOs and its synchronous wrapper waits for their completion.
The implementation review must check split-range completion and memory-pressure
behavior against the running kernel headers before selecting the async adapter.
This step changes neither SWZ nor physical-device admission. Heavy-CPU/low-RAM,
real swap semantics, representative churn and disposable-VM qualification remain
separate release gates.

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

## ID73 — CPU/cache qualification batch

Status: **implemented on `main`; native and loaded qualification required before
any optional policy promotion**.

This batch targets work that current phase timings made visible without changing
SWZ geometry, authority ordering or the default compression policy.

- **SSE2 delta64 load path:** forward transform retains the previous XMM pair
  and forms `[previous.high,current.low]` with `shufpd`, so each 16-byte
  output consumes one new 16-byte input load. The inverse forms its shifted
  prefix operand with register-only `pslldq $8`. Both remain byte-identical
  to scalar delta64. Native qualification checks emitted instructions and
  continues to report backend ns/page.
- **Validated metadata hits:** metadata from the direct validated cache,
  metadata set, or validated extent LRU uses descriptor-only lookup rather than
  recomputing metadata CRC and duplicate-record validation. Cold metadata and
  provisional ID63 coalesced bytes still run full `swapz_validate()`.
  Cached metadata sequence must match the observed authoritative map before
  any payload lower read; logical identity, generation, offsets, authority
  comparison and payload CRC still execute on every logical read.
- **Publication preflight:** `swapz_finish()` builds bounded old-extent and
  old-segment deltas in authority-owned scratch, validates aggregate mapped/GC
  accounting without touching global arrays, then applies each aggregate once.
  The old mutate/restore GC preflight and repeated per-record authority scans
  are removed. Paused transaction hashes cover only the active transaction
  prefix through `records[count]`; staging zero-initializes the transaction,
  and all semantically active header/record bytes remain protected.
- **Planner uniqueness reuse:** the generic planner retains duplicate-page
  defense. The private production batched path alone skips repeated duplicate
  scans after `swapz_validate_batched_pages()` has already proved the whole
  batch unique.
- **Early exact-zero routing:** after ordinary LZ4 returns a tiny candidate,
  the existing full-page zero scan runs before delta64 rescue and payload CRC.
  A true zero becomes the same logical hole as before and no payload bytes are
  copied into the ordered batch.
- **LZ4 acceleration evidence:** ordinary first-pass LZ4 exposes read-only
  `lz4_acceleration=1..4`, default 1. The delta64 second LZ4 remains fixed at
  1 because that path explicitly targets tight packing cliffs. Native
  qualification sweeps 1/2/3/4 on the same deterministic corpus, verifies
  round-trip bytes, and feeds each set of lengths to the real bounded planner.
  Do not promote a value solely because compressed bytes differ; compare CPU,
  planned blocks/extents, lower I/O, throughput and tails.
- **ID63 3+ opportunity evidence:** active coalescing remains the qualified
  two-range pair. Passive counters record 3+ physically adjacent admitted
  full extents whose combined span fits the existing eight-block/32KiB scratch.
  This conservative evidence must justify a later exact-missing-range chain
  implementation; no extra RAM or lower I/O is added here.
- **Production delta64 wrapper cost:** kernel status now reports transform calls
  and transform wall around the dispatched transform, which includes
  `kernel_fpu_begin/end` on x86. Compare this with raw native backend ns/page
  before using native transform economics to justify rescue policy.
- **Low-risk companion work:** validated extent-cache refreshes copy only
  missing blocks; slot priming never republishes provisional coalesced bytes;
  GC relocation reuses the payload CRC just verified by the read engine; the
  GC sorter uses the existing uniform-length identity fast path; successful GC
  no longer rewinds the allocator's circular probe, and equal-cost victim scans
  begin from that probe. These are allocator-fairness changes, not NAND wear
  claims.

Acceptance is byte-exact native correctness, sanitizer cleanliness, x86 SSE2
instruction-shape checks, W=1/W=2 kernel builds, and the existing owner-only
loaded matrix. For performance promotion require matched same-host evidence.
For `lz4_acceleration`, report per-setting compression CPU plus planner
blocks/extents and loaded lower WRITE bytes/requests. For delta64, report
wrapper-inclusive transform ns/call alongside raw backend ns/page. For ID63,
report the 3+ chain opportunity counters before implementing an active chain.

## Release gates

A release or physical-media trial remains blocked until the same pinned source has repeated byte-exact loaded correctness, genuine lower error coverage, sustained GC, bounded resource behavior, acceptable read p95/p99 and CPU/RAM, statistically defensible matched performance, and an independent safety review. Physical-device admission is not part of the current roadmap implementation.
