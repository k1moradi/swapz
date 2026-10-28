# Roadmap

**Immutable naming policy (read before every prompt):** The project is `swapz`; the kernel module is `dm-swapz.ko` (loaded as `dm_swapz`); the Device Mapper target is exactly `swapz`; and the module alias is `dm-swapz`. Never put implementation-generation numbers in product, module, target, source-path, report, workflow, helper, or schema names. `SWZ` is the current unversioned on-disk format identity; do not assign a format version until an incompatible format boundary is justified.

**Single official test command (read before every prompt):** Run `make test` at the repository root for every supported swapz test and benchmark. A complete run must report BLOCKED (nonzero) if safe noninteractive privileged qualification cannot run. Do not create, publish, recommend, or document alternative test commands. Private scripts and CI jobs are implementation details, not operator interfaces.

This file contains only active work. Completed experiments and detailed historical transcripts belong in Git history.

## Current baseline

The latest successful standard owner matrix tested exact source
`829cdbe0d9eb9541cc3954e3af02e821a90c5595` and published canonical
report-only commit `efb713c06daa4fc03fdd7a200032c9c243089850`. All five
`make test` stages passed, including loaded correctness/lifecycle, live GC,
DISCARD/TRIM, retained write/flush fault injection, packed placement, both
owned-RAM storage regimes and ID36 resource pressure.

The source is nevertheless not product-qualified against raw on fast mixed
service. At QD32, raw useful WRITE/READ is 62.96/20.90 MB/s. Async swapz is
32.21/10.69 MB/s, while lowering backing WRITE throughput from 62.96 to
24.00 MB/s and lower-WRITE requests from 12295.7 to 2572.6; READ p99 improves
from 4.57 to 1.21 ms. This is a trade-off: swapz preserves a strong
lower-device byte/request advantage but gives up too much useful service.

Fast sustained WRITE confirms the architecture can beat raw once enough useful
work is available. Async swapz versus raw is 19.30/22.22 MB/s at QD1,
68.52/84.00 at QD4, 82.50/85.81 at QD8 and 130.83/89.11 at QD32. The QD32
+46.8% direction proves compression and packing can outrun raw on the same
synthetic fast device; the QD4 -18.4% and mixed -48.8% directions show that
small-batch dispatch and idle-time elimination, not another compression
micro-optimization, are the immediate product bottleneck.

Production infrastructure remains ordinary LZ4 acceleration one, one unbound
asynchronous preparation producer, the bounded 64-slot RAW+compressed
reservoir, immutable lower-WRITE depth one, independent READ fan-out, the
eight-block ID63 cap, packed placement and SWZ 1/2/4-block extents. Delta64
remains default-off pending representative swap-content prevalence. Do not add
another producer, enlarge the reservoir or reopen K>1 until existing
preparation/ready-wait telemetry shows pressure.

The `829cdbe0d9eb` result refutes the active 500us suppressed-tail wake plus
cache-hit READ-pivot close policy. It passed correctness but regressed service:
relative to `e17f05a1c256`, fast mixed async useful WRITE fell 38.26 ->
32.21 MB/s, lower-WRITE requests rose 2255.0 -> 2572.6 and READ p99 rose
0.823 -> 1.208 ms. The next candidate therefore removes that policy and its
temporary lifetime telemetry rather than tuning its timeout.

## Current bottleneck ranking

The strongest current signal is accepted-work lower-device idle time caused by
small retained windows. On `829cdbe0d9eb`, the regressed mixed workload
records 756.58 ms in `accepted_work_lower_idle_undersized_batch_ns`. The
500us/cache-hit-pivot policy can close a two/three-record window just before its
third/fourth WRITE arrives; because such a close is below the existing
`count > 4 || preparation_queued > 0` asynchronous-detach gate, it performs a
synchronous lower WRITE and strands the companion records in a fresh window
that can then reach the full ordinary retention deadline.

Two bounded state defects are therefore the next ID83 candidate, with no new
resource concurrency:

1. **Mixed-wave finite-tail recognition.** Keep the four-record floor for a
   pure-WRITE wave. When the serialized worker has already serviced a READ in
   the active accepted wave, or the post-PACK sampler encounters an already
   accepted non-WRITE boundary, a two/three-record residue is finite accepted
   work and may become its exact one-shot target immediately. This uses one
   worker-owned boolean plus the sampler's existing prefix state; it adds no
   timer, mapper atomic or future-arrival wait.
2. **Persistent selective-pack recognition across RAW.** Preserve the refuted
   total-count-four first-pack guard, but once total count exceeds four retain
   proof that an earlier two-compressed-record/4KiB or
   three-compressed-record/8KiB prefix formed a valid pack. Re-evaluate that
   proof after RAW as well as compressed admission so RAW interleaving or a
   later compressed record cannot permanently erase pack readiness.

Performance hypothesis, not qualification: removing the failed timeout/pivot
path should first recover toward the pre-candidate ~38.26 MB/s fast-mixed
baseline by avoiding premature synchronous two/three-record closes. Finite
mixed-tail dispatch and the persistent pack latch should then reduce the
756.58 ms undersized-idle component and lower request fragmentation, so useful
mixed and QD4 throughput should rise without giving back the existing
lower-byte advantage. The analytical ~114 MB/s figure obtained by subtracting
measured lower-I/O+CPU work from the old wall time is an upper-bound opportunity
signal, not a throughput prediction; scheduler, read, publication and device
serialization costs remain.

Do not optimize LZ4 itself, add preparation workers, enlarge the reservoir or
restore K>1 in this round. The candidate must isolate dispatch/state behavior
and preserve the current ownership, RAW terminal-selection, ordering and
fail-closed rules.

## Optimization evidence table

This table is the canonical anti-retest index. Before proposing optimization
work, find the matching ID here. Keep each row compact: the current decision,
one evidence/report anchor when it materially helps, and the specific condition
that can reopen the question. Do not copy the experiment chronology into other
documents. Class 1/2/3/5 items are closed unless their row states a reopen
condition or a materially different workload/device invalidates the evidence;
Class 4 items are evidence-ready; Class 6 items are external gates.

**Three-host 2026-10-23 cleanup decision:** source `174d42eb7135` passed the
complete owned-RAM matrix on AVX-512, ARM64/NEON and SSE2. Ordinary first-pass
LZ4 acceleration selection, READ-coalescing cap selection, delta64 preparation
width K=2/K=4 and lower-WRITE depth-two are closed experiments. Production keeps
ordinary LZ4 acceleration 1, coalescing cap 8, delta64 preparation K=1 and
lower-WRITE depth 1; their runtime selectors and routine A/Bs are removed. The
current ordered-worker independent READ fan-out is distinct from the retired
`swapz-read` helper and needs one isolated on/off evidence cycle before a
keep/remove decision.

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
| 36 | Heavy-CPU plus low-RAM qualification | **1 historical qualification; watchdog hierarchy repaired, owner requalification pending** | The historical owner gate remains valid at source `ab56b41`. Report `761e22b85da1` on source `bf479c4420fa` reached swapz packed-read with positive pressure evidence (`memory.high` +15,126, CPU PSI +364,044,323 usec), no reported OOM/OOM-kill, then the 420s pair watchdog expired while its two sequential children were each allowed 280s. This was an impossible parent/child timeout hierarchy, not evidence that either child exceeded its own forward-progress limit. Keep the 576MiB pressure set, `memory.max=896MiB`, 2x niceness-10 CPU burners, allocation-bounded 32 persistent packed-read lanes and 280s per-candidate bound; set the pair watchdog to 680s (`2*280+120`) and the top-level ID36 helper to 720s. Owner pass still requires positive high/CPU-PSI deltas, zero OOM/OOM-kill, byte-exact readback and teardown. |
| 37 | K=1 ping-pong WRITE pipeline | **1 qualified / keep; release gate open** | Latest five-pair fast sustained-write evidence shows async/sync QD4 +1.66% CI [+0.33%,+3.00%], QD8 +23.88% [+18.52%,+29.24%], and QD32 +22.15% [+15.65%,+28.65%]. QD8 lower requests fall 17.96%; QD32 requests fall 9.96% while bytes are statistically neutral. Keep the fixed one-slot path and existing activation gates; low-RAM/heavy-CPU remains a release gate. |
| 38 | Shared accumulator with K>1 lower-write slots | **5 refuted / removed** | Repeated depth-1/depth-2 evidence did not establish a useful service benefit. Production is fixed at one slot, and the second-slot allocation/append path plus runtime selector are removed. Reopening K>1 requires a new workload and an explicit architecture experiment. |
| 39 | Latency-first bounded parallel READ service | **1 promoted / selector and routine A/B retired** | The retired `swapz-read` helper workqueue remains absent. The final five-pair ARM64 fast-model decision at source `11fbc839...`, with ID63 off, showed fan-out +17.9% mixed WRITE/READ throughput (95% CI +17.2..+18.5), -48.7% mixed READ p99, +67.9% sequential READ throughput and +101.8% seeded-random READ throughput while raw-control drift overlapped zero. Keep ordered-worker private-slot fan-out fixed on; remove the `parallel_reads` module selector and routine ten-session A/B. |
| 40 | Freeze first, then start LZ4/CRC | **5** | Rejected; compression belongs during collection. |
| 41 | Per-lane isolated write accumulators / 2xN packing queues | **5** | Reject by default; destroys global packing view and risks request inflation. |
| 42 | Explicit serial-vs-parallel lower queue model + lower in-flight-depth telemetry | **1 completed measurement** | Owner-qualified. Slow hwq=1 stays at sampled peak depth 1; fast raw reaches >1 while swapz remains at 1. Keep the geometry and telemetry as mandatory evidence for concurrency claims. |
| 43 | Huge/compound-page RAM input support (folio/THP/hugetlb), not only 4KiB page inputs | **1 qualified / covered** | Explicit multi-bvec, non-zero bv_offset, and THP compound folio backing qualified on owned RAM with kernel observation counters (`bio_segments_gt1`, `bio_segments_max`, `bio_nonzero_offset`, `bio_compound_folio_pages >= 128`, `bio_copy_fallback_pages`). Byte-exact across segmented, THP, and cross-mode reads/writes with zero failures. Larger base PAGE_SIZE/native larger records remain architecture work. |
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
| 55 | Learned burst-target PACK_READY site/geometry attribution | **1 completed measurement; ID77 is a distinct reopen** | Historical evidence showed admission-side burst closure and rejected changing policy from the site/size histogram alone. That conclusion still forbids small-target gating. ID77 reopens closure ownership only because the later `5f92ea3` run, after ID75 removed lower-READ preparation, leaves a significant async request/throughput regression and source inspection proves a separate post-K1 completion stranding path. Do not rerun the old site/geometry A/B; qualify ID77 against its explicit gates. |
| 56 | Post-PACK tail-sample timing vs detached K=1 state | **1 completed measurement** | Fast async records 604.2 tail0/inflight vs 0 sync, plus 116.4 tail1/inflight and 70.4 tail2+/inflight. The timing asymmetry is proven, but slow async also has many tail0/inflight samples without a throughput loss, so use a controlled active successor rather than declaring causality. |
| 57 | K=1-busy PACK_READY gate + completion-aware zero-tail preservation | **3 refuted by owner evidence; reverted** | Two qualified runs reproduce ~-42% fast-QD8 async/sync. Latest is -41.1%, CI [-45.8%,-36.4%], with QD8 target 12 and 274.8 deadlines; fast mixed adds +271.6 lower requests while service-dry closes rise +263.4. Restore ID56/pre-ID57 sampling/closure behavior and remove active ID57 counters. |
| 58 | Nonzero same-filled-page special representation | **4 low-priority representative-corpus evidence** | Current synthetic trace has 0/12,301 nonzero same-filled writes and 0 final live same-filled pages, so there is no benchmark opportunity. Keep the offline detector; do not add a production representation until representative swap content shows prevalence. |
| 59 | Exact-content page deduplication / shared payload ownership | **4 representative-corpus + architecture evidence** | Synthetic trace reports 12,301 resident duplicate opportunities from only 128 payloads and 1,024 final duplicate pages. This proves the analyzer, not production prevalence. Measure representative lifetime overlap before implementing collision-free verification, bounded refcounts, generation-safe COW and GC/DISCARD ownership. |
| 60 | Queued READ grouping within the same immutable extent | **5 refuted / retired** | Five matched hwq=1 rounds showed no request win and an unfavorable p99 direction; the qualified post-ID65 fast directional sample was also worse. Remove standalone slot grouping and its dedicated benchmark controls; ordinary reads keep the shared caches. |
| 61 | Foreground GC scaling / background-GC question | **1 ID61b owner-qualified / keep; broader background-GC question remains open** | Report `85aeac4` proves the production survivor list in loaded GC: 20 relocated pages produced exactly 20 relocation-list visits, `gc_choose_map_entries=0`, 1,280 segment-score visits, 20 victims/rotations and byte-exact verification of all 4,096 pages. The same qualified report's native scaling measured full-map relocation at 1.215/4.901ms versus 0.00169/0.00196ms for the 256-survivor list at 1/4GiB-equivalent scale. Keep the per-segment list; realistic foreground-GC stall/headroom evidence remains separate. |
| 62 | Real-device / physical-media qualification | **6 safety/deployment gate** | Still blocked. ID29 RAM qualification does not authorize physical storage, active swap, or a bypass module parameter. Real-device work requires separate owner authorization, device-loss acceptance, identity/alias checks, endurance/error metrics and independent safety review. |
| 63 | Physically adjacent distinct-extent READ coalescing | **1 owner-qualified / active default-on / cap fixed at 8 blocks** | Current report `dc78c9bbffbd` on exact source `0155a09a0f2e` reconfirms the active path. Fast sequential lower requests fall 11.29% (95% CI -14.35..-8.24) while throughput and p99 overlap zero. Serial-depth sequential requests fall 25.89%, p99 13.69% and throughput rises 30.58%, all significant. Keep exact 2..8-range zero-padding-free coalescing and the fixed eight-block cap. |
| 64 | One-shot in-flight-zero burst-target shrink guard | **5 retired** | Completion-aware zero-tail sampling made the trigger disappear: latest five matched rounds report after-I0=0 and skip-I0=0. Remove the branch/module parameter/A-B; retain only fixed-zero compatibility status tokens. |
| 65 | Retire ID39 `swapz-read` helper | **1 owner-qualified / keep** | The helper remains correctly retired and legacy helper status/CPU tokens stay zero. The latest owner run shows a separate ID63 fast-p99 regression even without that helper, so current cleanup targets private cache-copy/completion ordering rather than restoring read concurrency. |
| 66 | Zero-allocation multi-page DISCARD liveness prevalidation | **1 owner-qualified / keep** | Saves 6 bytes/physical 4KiB block (~1.5 MiB/GiB) while preserving all-or-nothing shared-extent liveness validation. Full loaded lifecycle/GC/TRIM/fault evidence passed. |
| 67 | Page-local delta64 rescue around LZ4 | **4 strong opt-in positive evidence; representative-content gate remains** | Current report `dc78c9bbffbd` on exact source `0155a09a0f2e` records 4096/4096 direct adoptions on the controlled positive fixture: useful WRITE +26.87% (95% CI +17.25..+36.49), p99 -20.93% (-23.24..-18.62), lower WRITE bytes -25.33% (-25.51..-25.14), while lower-request change overlaps zero. Keep default-off and collect representative anonymous-memory/page-corpus prevalence before any promotion. |
| 68 | Placement/reclaim telemetry | **1 owner-qualified / tail split added for ID69 evidence** | Report 711ceaad qualified aggregate placement/reclaim telemetry and ID70c. Aggregate hole counters continue to include segment-tail waste for continuity; separate tail-waste counters now let ID69 distinguish avoidable internal gaps from unavoidable segment-edge waste. |
| 69 | Hole-free 4KiB-aligned extent placement | **1 packed placement owner-qualified; aligned policy retired** | Report `013893fa` passed the repaired append-only segment-edge cases and loaded packed placement with 128 byte-exact pages, zero internal holes and zero hole-induced run splits. Aligned placement and its A/B harness remain retired; preserve tail-only waste and zero-split invariants without changing SWZ. |
| 70 | Segment DISCARD lifecycle | **1 ID70a + ID70c owner-qualified / keep** | Report 711ceaad shows 20 completed 1MiB GC TRIMs, 16 duplicate skips, plus one immediate upper-DISCARD TRIM followed by one reuse skip. Early/background async TRIM remains deferred. |
| 71 | Dead-segment allocation probe scaling | **1 owner-qualified / keep** | Report 712b98e0 shows 0.430->0.002ms at 1024 segments and 1.688->0.007ms at 4096 segments; loaded probing scanned 80/2497 candidates fully. Keep the mapped-count fast reject plus full zero-candidate scan. |
| 72 | Physical wear / logical allocator fairness | **1 terminal A/B completed; switch removed, circular fairness retained** | Five-pair 70%-occupancy 40,960-rewrite loaded benchmark on owned RAM proved circular probing naturally distributes opens evenly across dead segments (min 0, max 4, sum 172 in all runs; spread 4). Least-open scanning achieved 0.00% spread reduction while regressing write p99 latency by +9.93% (+18.0 us). Per the predeclared terminal protocol, the optional switch was removed and circular allocator fairness was retained as the sole canonical policy. Logical opens remain allocator fairness telemetry, never NAND P/E cycles. |
| 73 | Flexible/larger extent study | **5 larger/irregular classes deprioritized** | Report 711ceaad shows packed 1/2/4 captures the dominant geometry gain. A 3-block class saves only 2/2,089 blocks; 32/64KiB maxima save 14/22 more blocks while cold-read cost rises 1.47->1.53/1.55. Keep SWZ 1/2/4 classes unchanged unless a broader representative corpus materially overturns this result. |
| 74 | Modern storage service-envelope bottleneck attribution | **1 evidence complete; kernel concurrency stays closed** | Repeated fully qualified reports `1b711f242ee8` and `b4b8187cad6a` on source `38560803e0d0` complete all eight modern-SD/SATA/Gen4/Gen5 directional rows. Saved lower work translates strongly on the 500us SD model, but useful WRITE service regresses on SATA and both NVMe envelopes despite substantial lower-byte/request reduction. The explicit reopen signals remain small: K=1 ready-window wait stays below ~0.54% of wall across the fast-media rows and preparation wait/backlog is shallow, so neither lower-WRITE K>1 nor wider preparation is justified yet. The two same-source runs also expose submitter instability: raw Gen4/Gen5 controls range from roughly 80/333 MB/s to 174/1038 MB/s for mixed/write-only despite unchanged device models. Qualify a lower-overhead replay engine before interpreting multi-gigabyte capability or reopening kernel concurrency. |
| 75 | Mixed-I/O lower-READ preparation overlap and bounded full-batch ID63 gate | **1 owner-qualified cleanup / keep** | Source `5f92ea3` passed the five-stage owner matrix with lower-READ preparation starts fixed at zero. Versus the earlier `aa5237c` baseline, fast async-minus-sync lower-WRITE request excess fell from +319.8 to +45.6, while QD8/QD32 async gains remained positive. The residual request excess and -4.86% fast-mixed throughput delta are not explained by lower-READ preparation; keep the removal and move the remaining scheduling question to ID77. |
| 76 | Native modern-storage replay engine | **1 owner-qualified / keep** | Report `aa5237c` (tested source `329a10c`) completed the five-stage owner `make test` with `replay_engine=native-c` in both raw and swapz modern-envelope arms and byte-exact qualification. The replay confounder is therefore closed for those rows. Configured multi-GiB/s Gen4/Gen5 caps remain service-model inputs, not physical-media claims: use attained raw-control service as the host capability check. The qualified native replay strengthens, rather than weakens, ID74's conclusion that K>1 and wider preparation remain closed absent ready-run/backlog evidence. |
| 77 | Worker-owned PACK_READY and post-K1 completion re-evaluation | **1 owner-qualified / keep; residual moves to ID78** | Report `6c7d645924cd` on exact source `8a6dd2a` passes all five owner stages. Admission burst closes are now exactly zero, async-minus-sync lower-WRITE request excess improves from +45.6 (CI +13.9..+77.3) to +31.6 (CI -10.3..+73.5), and the throughput delta improves from -4.86% significant to -3.13% with CI crossing zero. QD8/QD32 async gains survive at +74.6%/+14.9%. Keep worker ownership. The remaining +49.8 burst-target closes and asymmetric post-PACK sampling are a distinct state-conservation defect tracked by ID78, not evidence to restore admission closure. |
| 78 | Completion-aware post-PACK generation conservation / RAW-safe pack recognition | **1 owner-qualified state repair / keep; performance recovery incomplete** | Exact ARM64/NEON source `ab885372` passed the full five-stage owner `make test`. It eliminates the catastrophic `c07edd9` deadline/target inflation and keeps completed-generation learning bounded, but it does not recover the earlier async throughput advantage: latest fast QD8 async/sync is -0.07% (95% CI -1.12..+0.98) and QD32 is -0.36% (-8.27..+7.54), while lower-WRITE requests regress +2.16% and +8.13% respectively; QD4 is -9.32% with a wide CI. Keep the completion-state repair and RAW-safe recognition as correctness/state hygiene, but do not claim a scheduling win. Same-source mixed evidence is heavily replay/load sensitive, so the remaining low-QD detachment question moves to ID80 rather than reopening K>1 or the refuted staged-only PACK_READY lockout. |

| 79 | Planned single-record exact read-cache invalidation | **1 owner-qualified READ-I/O win / keep; isolated causality A/B next** | Current report `dc78c9bbffbd` on exact source `0155a09a0f2e` retains the 9.0 fast mixed lower READ requests in both sync and async after ID80/ID81 removal. Versus qualified pre-ID79 `ab885372`, the fast synchronous metadata-set hit rate rises 42.94%->99.78% and lower READ requests 2328.4->9.0, while windows rise 694.8->1793.8 and lower WRITE requests 724.6->1818.2. The two production kernel trees are byte-identical outside `engine.c`, and their fast mixed fixture/trace/order match; cross-report throughput is still host-load-sensitive. Keep exact-range fencing in production, but run one temporary ID79-off source A/B to prove whether the lost lower-READ stall was accidentally providing WRITE batching. Do not retain a selector. |
| 80 | Shallow K=1 detachment eligibility | **5 owner-refuted / removed; restored pre-ID80 policy requalified** | Report `71251ba9232e` refuted ID80's static `count > 4U` gate with fast QD8 async/sync -9.1% (95% CI -15.1..-3.1). Current report `dc78c9bbffbd` on source `0155a09a0f2e` passes all five stages with the actual pre-ID80 predicate `count > 4U || preparation_queued > 0`; sustained QD4/QD8/QD32 async/sync throughput is +3.94% / +0.95% / +0.94%, with all three intervals overlapping zero. Keep ID80 removed and retain no dormant selector. |
| 81 | Cache-hit-neutral retained burst learning | **5 correctness-refuted / removed; rollback lifecycle requalified** | Exact source `26a045c80b56` passed build/native/W=1/W=2, then BLOCKED after 3.40s in owned-RAM retained suspend/drain because the lifecycle writer failed across suspend/resume (report `adc0aa8f3e1c`); no benchmark result from that source is valid. The bundled candidate also replaced the true pre-ID80 detach predicate with unqualified `count > 1U`. Current source `0155a09a0f2e` removes the whole bundle and passes retained suspend/drain plus the complete owner matrix in report `dc78c9bbffbd`. This proves the rollback is healthy but does not identify which ID81 sub-change caused the lifecycle failure; do not split or revive those changes without independent evidence. |
| 82 | Fast-media retained deadline and wakeup overhead | **4 evidence-backed candidate; measurement first** | Current exact source `0155a09a0f2e` shows Gen4 mixed 591.3 ms with 197 worker-empty deadline closes, 33.9 ms lower-WRITE service, 37.3 ms ordered-worker CPU and zero K=1 ready waits; Gen5 is 522.5 ms / 176 deadlines / 23.8 ms lower-WRITE / 32.3 ms worker CPU. At retain_ms=2, count*deadline proves at least 394/352 ms of aggregate deadline-reaching window age; it is not a pure-idle measurement. First add exact retained idle-wait and worker-wake attribution; then test a fast-media microsecond-scale or accepted-work-only closure policy without changing K=1, SWZ, ID63 or authority ownership. Reject if SD gains, lower-byte savings, lifecycle safety or mixed p99 regress materially. |
| 83 | Work-conserving admission queue + prepared reservoir + compressed/RAW dispatcher | **4 timer/pivot refuted; bounded mixed-wave + pack-state repair ready for owner qualification** | Exact source `829cdbe0d9eb`, report `efb713c06daa`, passes all five owner stages but refutes the 500us/cache-hit-pivot candidate: fast mixed async is 32.21 MB/s versus raw 62.96, lower-WRITE requests rise to 2572.6, and undersized accepted-work lower-idle reaches 756.58 ms. Remove the timer/pivot/lifetime state. Preserve the pure-WRITE four-record floor, but let already-observed mixed-wave boundaries make two/three-record tails finite immediately; separately preserve earlier valid compressed-pack geometry across RAW interleaving after total count exceeds four while keeping the count-four first-pack guard. Qualify only through public `make test`; K=1, one producer, 64 slots and SWZ stay fixed. |
| 84 | Four-record proven-dry mixed dispatch | **5 reported owner regression; superseded** | Reported exact-source `aec662bd` owner result (report commit `b729549f`) has fast mixed useful WRITE 35.27 MB/s versus the predecessor 39.41 MB/s, more undersized idle and WRITE fragments. Do not override authoritative sampled targets or detach a four-record K=1 run when preparation backlog is zero; retain the first-three inline LZ4 guard. |
| 85 | Independent-READ-transparent bounded post-PACK sampler | **4 candidate; owner qualification pending** | Count plain WRITEs across only accepted independent READs, with staged/earlier queued same-page checks, authority/fence rules and a 64-BIO scan cap. Retain the staged-only post-K1 rule. Hypothesis: fewer zero/singleton false tail samples, larger valid mixed WRITE windows, fewer lower WRITE requests and improved fast useful throughput; possible added CPU/early close. Require paired owner `make test` for raw/control, mixed/QD4/8/32, SD/SSD/NVMe, p99, GC, lower bytes/requests, and fault/lifecycle correctness before promotion. |
| 86 | Fresh independent-READ boundary for dry post-PACK 2/3 tails | **4 candidate / owner qualification pending** | Permit a dry 2/3-record post-PACK residue to close only after a successful independent READ serviced after that residue was staged, with no pending sample or active K=1 WRITE. This is distinct from stale earlier READ evidence and does not wait for compression or future BIOs; it leaves pure-WRITE and singleton policies intact. Hypothesis: reduce mixed worker-empty 2ms deadlines and improve useful WRITE latency while avoiding the unsafe unbounded preparation wait and four-record target hold proposed in the attached analysis. Risk: write fragmentation if cache-hit READ boundaries occur mid-wave. Require exact-source owner `make test` with paired raw/sync/async useful READ/WRITE, p99, lower IO, QD4/8/32, SD/SSD/NVMe, GC, and fault/lifecycle evidence before promotion. |

| 87 | READ-boundary observation across pending K=1 sampling and read fan-out | **4 candidate / qualification pending** | ID86 drops fresh post-PACK READ evidence while K=1's tail sample remains pending, and successful independent slot fan-out or parallel read-batch service omits the same observation. Record success in all three ordered-worker READ paths and retain it until the sample completes; a later staged WRITE or nonempty flush revokes it. The established close gates still prohibit active K=1, pending samples, sampled targets, singleton tails, non-post-PACK waves and non-dry accepted FIFOs. Hypothesis: fewer wasted 2ms tail deadlines and better useful mixed throughput/latency; risk: more small lower-WRITE requests or fragmentation. Require exact-source owner `make test` with raw/sync/async QD4/8/32, SD/SSD/NVMe, p99, lower bytes/requests, GC and lifecycle faults; rootless CI is supporting only. |

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

- **ID38:** settled for the current product. Lower-WRITE depth is fixed at one;
  the runtime selector, second-slot allocation/append path and routine depth-2
  A/B are retired. Ready-wait telemetry remains passive evidence only. Any
  future K>1 study is a new architecture experiment.
- **ID65:** owner-qualify the synchronous read-path cleanup; do not restore or
  replace the rejected helper workqueue unless new measured evidence requires it.
- **ID58/59:** keep representative-content collection offline.
- **ID61:** add foreground-GC stall/reserve-headroom evidence under bounded useful pressure.
- **ID62:** physical devices remain outside the current development safety scope.

## Immediate work queue

The latest owner-qualified exact source is
`829cdbe0d9eb9541cc3954e3af02e821a90c5595`, with canonical report-only
commit `efb713c06daa4fc03fdd7a200032c9c243089850`. All five owner stages pass,
so the next change is a performance-policy repair, not a correctness rollback.

1. Remove the refuted 500us suppressed-tail wake, cache-hit pivot close
   authorization and temporary `suppressed_tail_*` lifetime telemetry. Restore
   the ordinary first-record retention deadline as the only timer boundary.
2. Keep the qualified four-record floor for pure-WRITE post-PACK tails. Add
   worker-owned mixed-wave evidence so an already-serviced READ or accepted
   non-WRITE sampler boundary can make an existing two/three-record tail its
   exact one-shot target without waiting for future arrivals.
3. Preserve the total-count-four first-pack guard. For count greater than four,
   retain proof that an earlier selective two-record/4KiB or
   three-record/8KiB compressed prefix existed, and re-evaluate this proof on
   both RAW and compressed admissions.
4. Run the single public `make test`. Promotion requires correctness and
   lifecycle PASS plus material recovery in fast mixed/QD4 useful service,
   preserved QD8/QD32 direction, acceptable p99, and no material regression in
   lower-WRITE bytes/requests, slow/SD service, CPU/RAM/GC or ID36. Exact
   target-2/3/4 and accepted-work lower-idle counters remain the attribution
   evidence.
5. Keep one unbound preparation producer, the 64-slot reservoir, K=1, ordinary
   LZ4 acceleration one, packed placement, circular allocation, ID63 and SWZ
   geometry unchanged. The public qualification remains architecture-neutral:
   x86 must continue the SSE2/AVX2/AVX-512 native checks and arm64 the NEON
   checks, with runtime ISA execution only where the host advertises support.
6. If this candidate still leaves material accepted-work lower idle after the
   dispatch-state defects are removed, use that measured residual to decide
   whether a second producer, a larger reservoir or multiple lower-I/O buffers
   earns a new bounded experiment. Do not preemptively add those resources.

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
- **LZ4 acceleration evidence:** three-host loaded evidence closed the ordinary
  first-pass acceleration experiment without a repeatable service win.
  Production ordinary LZ4 is fixed at acceleration one and the runtime selector
  plus routine loaded 1/4 A/B are retired. Native qualification still sweeps
  1/2/3/4 as a byte-exact CPU/geometry regression check. Delta64's second LZ4
  retains its separate opt-in acceleration control.
- **ID63 bounded adjacent-range chain:** the active path now extends the
  qualified pair mechanism to 2..8 physically adjacent immutable extents when
  their exact missing ranges form one zero-padding lower read. The lower-read
  span remains capped by the existing eight-block/32KiB scratch. Eight private
  engines share one 64-page decode-output pool rather than multiplying 256KiB
  buffers. Conservative 3+ full-extent counters remain opportunity evidence;
  `parallel_read_coalesced_reqs_saved` records N-1 for an N-extent chain.
- **Production delta64 wrapper cost:** kernel status reports transform calls
  and wrapper-inclusive transform wall, including `kernel_fpu_begin/end` on
  x86. Current loaded/native comparisons put the wrapper premium in the
  hundreds-of-nanoseconds range while total rescue work is tens of
  microseconds per page, so FPU-transition batching is deprioritized relative
  to compression and scheduling work.
- **Delta64 preparation width:** async preparation owns one producer lane
  regardless of delta64 policy. Two-host K=1/K=2 evidence and earlier K=4
  regressions closed the concurrency question; the runtime preparation-width
  selector and routine K=2/K=4 qualification are retired. Predictor scratch
  allocation remains conditional on rescue being enabled.
- **Low-risk companion work:** validated extent-cache refreshes copy only
  missing blocks; slot priming never republishes provisional coalesced bytes;
  GC relocation reuses the payload CRC just verified by the read engine; the
  GC sorter uses the existing uniform-length identity fast path; successful GC
  no longer rewinds the allocator's circular probe, and equal-cost victim scans
  begin from that probe. These are allocator-fairness changes, not NAND wear
  claims.
- **Scalar hot-path follow-up:** bounded planner fit/candidate evaluation,
  batched-run setup, publication preflight, READ eligibility, metadata lookup
  and SWZ descriptor validation avoid redundant scans/branches after the same
  operation has already proved the required invariant. This changes no SWZ
  bytes, extent classes, scheduling policy, lower-I/O depth, authority order or
  cache capacity. Treat it as CPU-work reduction only: exact-source
  qualification must preserve byte-exact output and lower bytes/requests, and
  any performance claim must compare useful service plus planner/publish/read
  non-I/O attribution against the pre-change `9202ce7` baseline.
- **Structural proof reuse:** after the scalar pass is qualified, publication
  authenticates metadata CRC once and folds descriptor adjacency/transaction
  identity into the existing Phase 1 walk; batched staging/appending reuse the
  window-wide uniqueness proof for their quadratic scans; and replay completion
  finishes through the CRC-authenticated authority-owned active transaction.
  Public validators/staging remain defensive. This remains CPU-only evidence:
  use `329a10c` as the immediate pre-change baseline, preserve exact geometry
  and lower-I/O invariants, and require owner `make test` before any
  performance promotion.

Acceptance is byte-exact native correctness, sanitizer cleanliness, x86 SSE2
instruction-shape checks, W=1/W=2 kernel builds, and the existing owner-only
loaded matrix. For performance promotion require matched same-host evidence.
For `lz4_acceleration`, report per-setting compression CPU plus planner
blocks/extents and loaded lower WRITE bytes/requests. For delta64, report
wrapper-inclusive transform ns/call alongside raw backend ns/page. For ID63, report both the conservative 3+ opportunity counters and active
request savings; any 3+ promotion requires exact-range native coverage plus
matched loaded lower-request, throughput and p99 evidence.

## Release gates

A release or physical-media trial remains blocked until the same pinned source has repeated byte-exact loaded correctness, genuine lower error coverage, sustained GC, bounded resource behavior, acceptable read p95/p99 and CPU/RAM, statistically defensible matched performance, and an independent safety review. Physical-device admission is not part of the current roadmap implementation.


### Alpha.29 loaded qualification observability repair

After alpha.29 portable qualification, an owner `make test` was observed with
no terminal output after stage 4. This exposed a harness defect independent of
the benchmark verdict: stage 5 was fully captured by `subprocess.run()` and
had no visible progress until all loaded work returned. The harness now streams
the existing phase markers live and wraps each privileged top-level helper in a
root-owned outer watchdog. This does not qualify ID83 and does not change
production kernel behavior; it makes any subsequent loaded stall attributable
to an exact smoke/benchmark phase and bounded in time. The first owner rerun
then exposed a second harness-only regression: the watchdog executed private
shell helpers directly, adding an executable-bit requirement that the previous
`bash helper.sh` privilege path did not have. The bounded wrapper now invokes
those helpers through `bash` inside `timeout`, preserving the original helper
contract while keeping the outer deadline. Live stage-5 output is also filtered
to concise phase transitions and failure/block diagnostics; full raw evidence is
still captured for the report instead of flooding the terminal with status and
JSON records. A later rerun after an async kernel stall exposed a third recovery
issue: stale-open cleanup signaled holders before proving that the mapper's lower
device was private harness RAM. Preflight now completes the exact mapper/UUID and
memory-backed null_blk proof first, then targets only the canonical owned DM node.
A holder that remains open after bounded TERM/KILL is reported as requiring a
host reboot; force removal remains forbidden. The next owner rerun exposed a
repository-mode regression in that repair: `loaded-preflight.sh` had lost its
executable bit, while rootless qualification only syntax-checked the file. The
helper mode is restored and rootless qualification now locks it; status-two
preflight runtime exits also surface a concise live failure marker instead of
being reduced to a generic missing-diagnostic verdict. The following owner rerun
then exposed that an earlier malformed repair had re-entered history as a
duplicated tail in `source-contract-test.py`. The file is rebuilt from the
known-good baseline with only the intended stale-recovery assertions, and
rootless qualification now rejects multiple terminal test runners. The next
owner run reached preflight but returned shell status 2 before any normal safety
diagnostic. The stale-recovery path no longer depends on Bash extended-regex
capture state for mapper/UUID/lower/open validation: it uses exact shell
patterns, a guarded dependency parser, and separately checked canonical-device
stats. This preserves the same positive-ownership boundary while converting
malformed or unexpected state into explicit `BLOCKED:` results instead of an
opaque shell-runtime status. The numeric internal-error trap remains as a
last-resort diagnostic. A subsequent owner run exposed one stale native interface assertion that still required the removed regex literals; that contract is aligned with the exact-token ownership checks and now explicitly rejects reintroduction of `BASH_REMATCH`. The following loaded owner rerun still returned shell status 2 before a safety verdict, so the remaining runtime `=~` expressions and C-style arithmetic commands are removed from privileged preflight as well. Canonical decimal validation, exact shell patterns and fixed bounded retry iteration now cover the path end-to-end without weakening positive ownership checks. The following native rerun exposed three stale harness assertions that still required the removed arithmetic spellings (source contract, Make interface contract, and rootless literal grep); all three are aligned to the non-arithmetic preflight forms in one change. The following loaded qualification run exposed that the multi-line `case` pattern in `loaded-preflight.sh` omitted trailing backslashes on continuation lines, triggering a Bash syntax error (unexpected newline) and exit status 2 before execution. The continuation lines are escaped with `\`, and `test-rootless.sh` is updated to invoke `bash -n` individually across every shell harness script so future syntax regressions fail in Stage 2 rather than during privileged loaded execution.
