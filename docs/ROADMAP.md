# Roadmap

**Immutable naming policy (read before every prompt):** The project is `swapz`; the kernel module is `dm-swapz.ko` (loaded as `dm_swapz`); the Device Mapper target is exactly `swapz`; and the module alias is `dm-swapz`. Never put implementation-generation numbers in product, module, target, source-path, report, workflow, helper, or schema names. `SWZ3` is reserved for the on-disk format identity.

**Single official test command (read before every prompt):** Run `make test` at the repository root for every supported swapz test and benchmark. A complete run must report BLOCKED (nonzero) if safe noninteractive privileged qualification cannot run. Do not create, publish, recommend, or document alternative test commands. Private scripts and CI jobs are implementation details, not operator interfaces.

This file contains only active work. Completed experiments and detailed historical transcripts belong in Git history.

## Current baseline

Owner qualification of `66a0d67bc09d91536a0c3bdc72aa7d0f2edacecf`
passed all five stages; report-only commit
`0956f85e9e49191ab0f68d01c738dca1def1162c` is the canonical result. These
remain owned-RAM `null_blk` synthetic models, not physical-media claims.

Fast mixed async remains statistically faster than sync but still misses the
predeclared >=5% materiality gate: 23.52 versus 22.70 MB/s, paired +3.7% with
95% CI [+1.3%, +6.0%]. The async lower-WRITE request penalty is +46.4 requests,
CI [+8.1,+84.7], so residual fragmentation remains real.

ID50 remains qualified with the ordinary deadline. Fast D/C/DL/I/O is
110.8/78.3/32.5/0/0 and only 2.0 companion resolutions occur after 1 ms. ID53
therefore stays permanently rejected; no active age cutoff is justified.

ID37 is now repeatedly qualified at fast write-only QD8. The latest five matched
rounds give +17.6% async/sync, 95% CI [+1.3%, +33.9%], following the earlier
+20.8% and +14.4% confirmations. Fast QD4 is +9.2% directionally and now merits
the same five-pair confirmation. Keep K=1 infrastructure; no evidence justifies
K>1 lower-WRITE slots.

ID39 remains qualified as a bounded Kread=2 mechanism. The latest same-cache
five-pair result makes sequential p99 significant at -12.1%,
CI [-20.4%,-3.7%], while seeded-random is -0.7% with a CI crossing zero. The
previous qualification showed the opposite pattern (random significant,
sequential near-significant). Across runs the useful tail benefit varies by
access pattern, but physical traffic does not inflate. Keep Kread=2 unchanged.

ID54 again isolates learned burst-target closure. Fast sync/async PACK_READY
causes are tail<=4 56.2/48.0, tail 127.8/67.8, burst 18.0/126.0 and
service-dry 628.4/613.0. Five matched async-minus-sync deltas are tail -60.0
CI [-82.7,-37.3], learned burst +108.0 CI [+64.3,+151.7], and service-dry
-15.4 with a CI crossing zero.

ID55 is now a completed measurement. Every learned burst-target close in both
modes occurs at admission: 18.0/126.0 sync/async; worker-tail is 0/0. The async
excess spans all learned-target bins rather than one small target:
<=4 +12.6 CI [+6.2,+19.0], 5-8 +23.4 [+6.0,+40.8], 9-16 +22.8
[+14.3,+31.3], and 17-64 +49.2 [+15.4,+83.0]. Actual close-count excess is
concentrated even more strongly at 17-64: +84.0 CI [+45.5,+122.5].
Overshoot contributes +82.4 CI [+49.4,+115.4]. The final retained burst target
is 27.8 sync versus 26.0 async, delta -1.8 with CI crossing zero. Therefore
neither a small-tail gate nor a generic small-target gate is supported.

ID56 is the passive successor. It partitions every post-PACK_READY tail sample
by tail=0/1/2+ and whether a detached K=1 write is still active, and counts
actual retained-burst target grows/shrinks. This directly tests the remaining
code-level hypothesis that async consumes an empty tail sample before lower
completion/upper BIO release. ID56 changes no readiness predicate, sample
consumption rule, target rule or timer.

ID24's boundary `sum_exec_runtime` sample remains only a lower bound. The
latest fast preparation callback reports 52.2 ms wall, only 2.2 ms scheduler
delta, but 36.8 ms of independently measured non-sleeping phases. Ordered
callback is 960.4 ms wall, 277.6 ms scheduler delta, with an 88.3 ms measured
phase floor. Do not use the boundary metric alone to justify N=2 or affinity.

## Current bottleneck ranking

These overlapping wall counters are diagnostic, not additive. In the latest
mixed run lower WRITE remains the largest measured WRITE-path wall at about
601.7 ms slow / 177.0 ms fast. LZ4 preparation is 140.8/77.4 ms and commit
non-I/O is 54.9/36.6 ms. Snapshot pause CRC remains only 1.7/1.1 ms; planner and
explicit copy costs are secondary.

READ amplification is no longer the active defect. The shared extent cache is
qualified independently and bounded Kread=2 remains useful without traffic
inflation. The latest five-pair run makes sequential p99 significant
(-12.1%, CI [-20.4%,-3.7%]); the prior run made seeded-random significant.
Keep the READ algorithm unchanged rather than broadening concurrency.

WRITE fragmentation remains the leading scheduling question on the fast mixed
model. Async uses 938.2 lower WRITE requests versus 891.8 sync. ID54/55 now
localize the residual difference to admission-side learned burst-target closure
(+108.0), predominantly large-count/overshoot behavior rather than a smaller
final target. ID56 now tests whether premature post-PACK tail sampling while
K=1 is still active is the upstream cause before any scheduling rule changes.

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
| 29 | Dead-segment DISCARD/TRIM | **4** | Synthetic victim distribution remains qualified; bounded owned-RAM experiment is ready. |
| 30 | Tiny microsecond grace timer | **5** | Refuted and deleted. |
| 31 | Shared descriptor queue + multiple unbound prep workers | **4 dependent** | Serial still has no preparation backlog and fast remains shallow (~0.21/0.06 at lower-WRITE boundaries). Consider N=2 only after repeated fast-QD8 evidence plus trustworthy on-CPU attribution. |
| 32 | One affinity-pinned worker per physical core | **3** | Reject affinity form. |
| 33 | Linux kernel CRC32C primitive | **1** | Already implemented; keep architecture-selected kernel backend. |
| 34 | Hand-selected SIMD/instructions beyond kernel/LZ4 | **6** | CRC is measurable, but verify active backend/on-CPU cost before bypassing kernel primitives. |
| 35 | Firmware/device/upper/lower compute offload | **6** | Hardware/interface dependent. |
| 36 | Heavy-CPU plus low-RAM qualification | **6** | Mandatory before multi-worker/pipeline promotion. |
| 37 | K=1 ping-pong WRITE pipeline | **1 qualified at fast write-only QD8; QD4 confirmation ready** | Third consecutive fast-QD8 five-pair result is +17.6%, CI [+1.3%,+33.9%]. Fast QD4 is +9.2% directional and now gets five matched pairs. Mixed is +3.7% CI [+1.3,+6.0]% but carries +46.4 lower requests. Keep K=1; do not add slots. |
| 38 | Shared accumulator with K>1 lower-write slots | **5** | Stronger hold. Serial hwq=1 has no parallel service slot. Fast hwq=64 has capacity, but K=1 run occupancy is only ~0.09 and preparation backlog is shallow; there is no sustained ready-run pressure for K>1 yet. |
| 39 | Latency-first bounded parallel READ service | **1 bounded mechanism qualified / keep** | Latest sequential p99 is -12.1%, CI [-20.4%,-3.7%]; random is -0.7% and inconclusive. Prior qualification significantly favored random. Benefits vary by access pattern without traffic inflation; keep Kread=2 and do not broaden depth. |
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
| 54 | Passive PACK_READY primary-cause attribution | **1 completed measurement** | Latest five-pair fast evidence strengthens the split: tail -60.0 CI [-82.7,-37.3], learned burst +108.0 CI [+64.3,+151.7], dry -15.4 inconclusive. Small-tail/service-dry policy changes are refuted for the residual excess. |
| 55 | Learned burst-target PACK_READY site/geometry attribution | **1 completed measurement** | All burst closes are admission-side (18.0/126.0 sync/async; worker 0/0). Excess spans all target bins; count17-64 is +84.0 CI [+45.5,+122.5] and overshoot +82.4 [+49.4,+115.4]. Final target delta is insignificant. Do not gate only small targets. |
| 56 | Post-PACK tail-sample timing vs detached K=1 state | **4 instrumentation implemented pending owner evidence** | Count tail=0/1/2+ separately while `inflight_write.active` vs idle, plus actual burst-target grows/shrinks. Exact sample conservation; no policy/timer/target change. If async-only tail=0-inflight dominates, a later bounded fix may defer only that zero-tail consumption until K=1 finalization. |


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

1. Owner-qualify passive ID56 and the expanded fast-QD4/QD8 five-pair harness.
   Keep all window readiness, target and timer policy unchanged in this source.
2. If ID56 shows that async disproportionately consumes `tail == 0` while
   `inflight_write.active`, implement one bounded successor that preserves the
   pending tail sample/serviced chain until K=1 finalization before accepting
   zero as a real burst boundary. Do not alter tail==1 ID50 deferral.
3. If ID56 does not localize that path, add only the smallest missing
   grow/shrink antecedent evidence; do not gate small targets generically.
4. Keep ID37 K=1 and ID39 Kread=2 unchanged. Use fast QD4 confirmation to
   locate K=1's usefulness threshold; QD8 remains a regression control.
5. Obtain trustworthy external scheduler CPU accounting before N=2
   preparation workers or affinity experiments.
6. Proceed independently with bounded owned-RAM DISCARD/TRIM (ID29),
   huge/compound-page coverage (ID43), and heavy-CPU/low-RAM qualification.

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
