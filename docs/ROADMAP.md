# Roadmap

**Immutable naming policy (read before every prompt):** The project is `swapz`; the kernel module is `dm-swapz.ko` (loaded as `dm_swapz`); the Device Mapper target is exactly `swapz`; and the module alias is `dm-swapz`. Never put implementation-generation numbers in product, module, target, source-path, report, workflow, helper, or schema names. `SWZ` is the current unversioned on-disk format identity; do not assign a format version until an incompatible format boundary is justified.

**Single official test command (read before every prompt):** Run `make test` at the repository root for every supported swapz test and benchmark. A complete run must report BLOCKED (nonzero) if safe noninteractive privileged qualification cannot run. Do not create, publish, recommend, or document alternative test commands; the sole owner-approved exception is the development decision loop `make fast_test`, which never qualifies a source, never writes or publishes `test_results.json` and never replaces `make test`. Private scripts and CI jobs are implementation details, not operator interfaces.

This file is the project's **rolling engineering blueprint**: active priorities, proposals, decisions and acceptance gates. Linux MM/swap/zswap semantics and implementation context live in [context.md](context.md). Completed experimental transcripts belong in Git history.

## Previous comparison baseline

The prior official owner `make test` passed all five stages on production
source `0f5db1f8a771` (report `08a4b855f541`), which carries ID101–ID104.
Fast QD32 mixed useful WRITE/READ is 69.69/23.13 MB/s versus raw 62.94/20.89
(+10.7%, READ p99 0.85 vs 4.32 ms) and SD mixed is +405%; fast QD1/QD4/QD8/QD32
are -5.2/-11.9/+25.4/+54.5% and SD QD1/QD4/QD8/QD32 -3.1/+260/+242/+264%. Lower
WRITE bytes per useful byte stay ~26–31% below raw with 79–91% fewer requests.
Storage envelopes (swapz/raw useful WRITE) on the medium mixed fixture: SD card
3.35, SATA 0.53, NVMe Gen4 0.54, Gen5 0.60. The report's `delta64_rescue=1`
envelope rows replay a different fixture (delta64-positive, write-only QD32,
whose raw control is ~4x faster on NVMe), so they are not a delta64 off/on A/B;
the same-fixture paired A/B is ID67. Lower host WRITE bytes are an endurance
proxy, not NAND wear measurement.

## Previous qualified source (ID107–ID108)

Exact source `03becc01802b` passed all five owner `make test` stages; report
`b5227ca58001` records that qualification. Fast mixed async useful WRITE
is +7.4% versus raw (READ p99 0.88 vs 3.71 ms), SD mixed is +393%, and fast
QD1/QD4/QD8/QD32 are -2.7/-10.2/+18.2/+56.3%. This single qualification run
preserves host-WRITE savings but does not establish SATA/NVMe or QD4 parity.

The later owner run on `de79f2ec832d` (report `a4ff2205fa95`) passed stages
1–4 and loaded correctness smoke, then failed the first mixed swapz session:
`profile_epoch` returned success without exporting its acknowledgement. The
callback now returns DM's success-with-output value 1, covered by an executable
rootless regression. The subsequent owner run on `b86fefd` passed, as below;
the failed run itself establishes no performance for the new delta64 defaults.

The preceding directional `make fast_test` observations were
(absolute swapz useful WRITE MB/s; raw varies ~5%):

| Scenario | 0f5db1f | Candidate | vs raw |
|---|---:|---:|---:|
| SATA mixed QD32 | ~188 | 216–223 | -51% -> -42..-45% |
| NVMe Gen4 mixed QD32 | ~324 | 332–345 | -50% -> -36..-44% |
| Fast mixed / QD8 / QD32 | unchanged within noise | | +11% / +30% / +36..+50% |
| Fast QD1 / QD4, SD mixed / QD32 | unchanged within interleaved A/B noise | | |

Lower WRITE bytes remain ~0.69–0.74 of raw in those development observations.
The owner run qualifies this source on owned RAM; cross-host architecture
coverage and repeatable product performance remain distinct evidence gates.

## Current qualified source and newer development

Current source `d2b66acb8c7eed99bbcfb6c89000df2da743ec83` passed all five
ARM64 stages, report `77a0c3c587d4194d519edef4f1c2b8eadd253a9f`, including
ID143's published-ACK handoff. The new loaded gate observed 602 handoffs,
verified 128 final pages and exactly 16,512 successful upper WRITEs across
suspend/resume, then observed seven handoffs before a later injected WRITE
failure and verified a fresh syscall returned EIO. The RAW gate verified 2,048
pages with 182 async READ batches and 768 lower READ requests. ID36 passed with
16,117 memory.high events, 732,389,376 peak bytes and 14 CPU pressure workers.
Automatic history refresh succeeded with 56 ARM64 PASS reports. Default mixed
useful service versus each report's raw control is +407.2% serial, +7.8% fast,
+274.7% SD-card, -43.6% SATA, -40.8% NVMe4 and -37.2% NVMe5. These are qualified
synthetic observations, not causal cross-report gains; the modern mixed controls
remain LZ4-only. Current-source x86 qualification is still outstanding.

Previous source `a9bfe44c253271dc928cde0593c2e0f6236d24ec` passed all five
ARM64 stages, report `1e8a5bbf8965f4857c8366ea6bb5a2416ddcbe88`, with the
RAW READ fan-out in ID129. The added all-RAW/balanced correctness gate verified
2,048 pages and observed 172 async READ batches. Default medium fast mixed
useful WRITE is 68.49 versus raw 62.98 MB/s (+8.7%); lower WRITE bytes per useful
byte remain about 26% below raw. Fast QD1/4/8/32 is -1.4/-12.0/+24.6/+60.2%.
These owner means qualify this source; the prospective source A/B in ID129
separately establishes the RAW-content gains and leaves medium changes
inconclusive. Automatic history refresh succeeded with 55 ARM64 PASS reports.

Earlier owner source `b86fefd9e364727fa002ebd891ef4adfbd1166b1`, report `0d97e99`,
passed all five stages with delta64 rescue on and second-pass acceleration 4.
Fast mixed useful WRITE is +10.8% versus raw; fast QD1/4/8/32 is
-4.9/-11.3/+28.4/+50.0%. SD mixed is +404%. These are this VM's synthetic
results; the mixed fixture made no rescue attempts and cannot establish
representative-content prevalence. ID115 holds the paired positive evidence.

Newer source `005592d` implements DELTA64_SHUF8 and the faster NEON inverse
(ID116–ID117). Its ARM64 rootless, warning builds, loaded correctness smoke
and positive-fixture pair passed. Owner x86 source `005592d` subsequently passed
all five stages (report `4886c4d`), including scalar/SSE2/AVX2/AVX-512 runtime
checks and resource pressure. ARM64 source `3362fa0` (same production C as
`005592d`) then passed all five stages, report `87180ee`. Do not attribute the
old plain-delta64 report to this encoding or pool the two hosts.

The x86 paired positive-fixture rescue comparison reports useful WRITE
124.80 -> 319.55 MB/s (+156.2%, paired 95% CI +146.4..+165.9%), lower WRITE
bytes -73.7% and p99 -94.0%. Lower requests rise 43.4% (160 -> 229.4): byte
savings and useful service improve, but request fragmentation remains a trade-off.
Fast mixed is +48.7% versus raw on that host; these x86 results do not replace
the ARM64 VM's baseline or establish representative anonymous-memory prevalence.

The new ARM64 matrix reports fast mixed +9.9% and SD mixed +400% versus raw;
fast QD1/4/8/32 remains -3.7/-11.7/+21.7/+52.2%. Its five matched positive
rescue pairs give 138.05 -> 309.69 MB/s useful WRITE (+124.4%, paired 95% CI
+118.4..+130.3%), lower WRITE bytes -73.4%, p99 -93.9%, and requests +7.1%.
This is strong controlled-content service/byte evidence with a request trade-off,
not evidence that ordinary mixed pages benefit from the transform.

The worker-quantum repair in `b30b2ab` (ID123) subsequently passed all five
ARM64 stages, report `8458690`. Fast mixed useful WRITE is 68.20 MB/s versus
raw 62.94 MB/s (+8.4%); lower WRITE bytes per useful byte remain about 26% below
raw. This establishes correctness and measured service for the repaired budget,
not a causal speedup over the preceding source.

## Current bottleneck ranking

1. **SATA/NVMe mixed (-36..-45%).** Traced SATA waves (median, 545 waves):
   32 replay threads arrive over ~99 us (raw: ~61 us, less CPU contention); the
   first K=1 lower WRITE leaves at ~56 us, stragglers stage behind it and the
   second WRITE leaves ~17 us after the first completes but ~100 us after the
   last straggler arrived; ~37 us of finalize/wakeup/acknowledgement trails the
   last completion. Wave ~368 us versus raw ~184 us. A single merged WRITE per
   wave would at best tie raw here (fixed 100 us device latency dominates both),
   so the remaining loss is the serialized second WRITE plus ordered-worker CPU.
   Waiting for stragglers (ID109) trades the same time it saves. The fresh
   post-ID107/ID108 K=2 experiment (ID110) reached depth two but did not improve
   useful service and increased requests. Profile ordered-worker CPU and
   arrival-to-dispatch timing before changing concurrency again.
2. **Fast QD4 (-12..-15%, bimodal).** K=1 completes all four writers together,
   so their reissue spread sits on every cycle while raw overlaps it. Parity
   was hypothesized to need overlapping lower WRITEs; ID110 did not improve
   it because four-record windows without followers still dispatch synchronously.
   Reopening needs a separately justified shallow-window ownership policy.
3. **QD8 bimodality and the 8KiB READ-amplification cap.** Unchanged from the
   ID101–ID104 analysis: merged eight-record windows win, and accepted-burst
   extents are capped at 8KiB, holding QD8 lower bytes near 0.75.

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
`swapz-read` helper. Its RAW extension has isolated source A/B evidence and
exact-source owner qualification in ID129; retain that scope rather than
extending its result to every compressed/cold-READ workload.

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
| 24 | Trustworthy kernel-worker on-CPU attribution | **2 boundary metric insufficient; scope corrected by ID131** | Historical fast prep is 52.2 ms callback wall / 2.2 ms scheduler delta / 36.8 ms partial phase wall; ordered is 960.4 / 277.6 / 88.3 ms. Boundary deltas are diagnostics, not guaranteed lower bounds; phase wall includes preemption and is not CPU. Require external scheduler accounting before N=2/affinity decisions. |
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
| 67 | Page-local delta64 rescue around LZ4 | **4 default-on by owner decision (ID115); representative-content gate remains** | Current report `dc78c9bbffbd` on exact source `0155a09a0f2e` records 4096/4096 direct adoptions on the controlled positive fixture: useful WRITE +26.87% (95% CI +17.25..+36.49), p99 -20.93% (-23.24..-18.62), lower WRITE bytes -25.33% (-25.51..-25.14), while lower-request change overlaps zero. Default-on since ID115 (owner decision); representative anonymous-memory/page-corpus prevalence decides whether it stays on. |
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
| 88 | Owned retained WRITE-fault BLOCKED: device-node identity and fail-closed diagnosis | **4 root-cause isolation / exact-source owner repeat required** | Source `08e9ce0d34a1` passed build/native/W=1/W=2, oracle, GC, DISCARD and suspend, then BLOCKED when a single direct WRITE unexpectedly succeeded with test_fail_write_nth=1. The test checked dmsetup's UUID but did not prove that /dev/mapper after repeated remove/create pointed to the same DM device. The harness now validates the opened node's sysfs UUID/name and reports the armed hook's counters if the write still succeeds. This removes a wrong-device false qualification path but is not proof that udev was the actual cause; if calls=1 and injected=1 despite success, fix upper BIO completion/error propagation before any performance work. Re-run full owner `make test` on the exact source. |
| 89 | Pre-submission retained WRITE error propagated to upper BIO | **Owner loaded gate pending** | The ID88 owner report authenticated the exact mapped node and recorded `write_fault_calls=1 injected=1 failed=1 zero_pages=0`, yet direct `dd` returned success. This eliminates the stale-node theory and proves the synthetic lower fault was armed, not that the upper WRITE completed in error. Protect `swapz_complete` against new success on an already failed target; count actual upper WRITE BIO success/error completions and require exactly one upper WRITE error after the injected fault. Native source and kernel compile tests validate code paths but cannot prove original user-process error propagation: owner `make test` remains the sole acceptance gate. |
| 90 | Retained synthetic WRITE error survives DM clone boundary | **Owner loaded gate pending** | The owner test for `e9122f3` reports `calls=1 injected=1 failed=1 upper_write_ok=0 upper_write_err=1 logical_write_bytes=0` but direct `dd` still returns zero. Kernel 6.12's Device Mapper `clone_endio()` passes clone errors to the original bio, which the previous counter did not inspect. Add a target `end_io` fail-closed guard and distinct pre-DM-boundary counters; neither native CI nor those counters qualify userspace error propagation. Accept only after owner `make test` sees the direct injected WRITE fail and all subsequent loaded phases pass. |
| 91 | Replace ambiguous retained WRITE-fault process probe with exact O_DIRECT syscall oracle | **Owner loaded gate pending** | The owner test for `42347a9` records `upper_write_err=1 endio_seen_err=1 endio_seen_ok=0 logical_write_bytes=0`, proving the target clone reached Device Mapper with an error. Linux 7.0 block-device synchronous direct I/O waits for BIO completion and converts final BIO status to errno, while GNU dd separately wraps write(2) and process exit behavior. Qualification now uses a tiny aligned `O_DIRECT` `pwrite(2)` helper that exits zero only for exactly `-1/EIO`; success, partial I/O, a different errno, setup failure or timeout remains BLOCKED with numeric syscall evidence. This changes the oracle, not the kernel fault policy. Accept only after owner `make test` passes this loaded gate and the remaining stages. |
| 92 | Loaded WRITE-fault marker parser drift after exact syscall oracle | **Root-cause fix / owner requalification required** | Owner `make test` on `fdcd5c6456f0` completed every loaded smoke subphase including `PASS_RETAINED_SYNTHETIC_WRITE_FAULT`, `PASS_RETAINED_SYNTHETIC_FLUSH_FAULT`, packed placement, both RAM regimes, storage envelopes, delta64/read-coalescing A/B, sustained QD sweeps and ID36 resource pressure. Stage 5 still FAILed with `missing loaded correctness markers: write_fault` because `parse_loaded_correctness()` required the pre-ID91 marker without `syscall_errno:EIO`. Synchronize the parser with the exact aligned-pwrite marker and native synthetic fixture, rejecting missing/wrong errno and incorrect fault/lower-I/O numbers. This is a report-contract bug, not proof of a kernel regression; rootless CI plus the owner’s already-executed loaded data support the diagnosis, but only an exact-source owner `make test` can requalify the full matrix. |
| 93 | ID36 mixed replay under memory.high occasionally exhausts its per-candidate deadline | **Harness allocation fix / owner loaded qualification pending** | The owner `make test` on `69e7f2643627` passed build/native/W=1/W=2, owned smoke, retained WRITE/FLUSH faults, both mixed RAM models, storage envelopes, delta64/coalescing A/B and all sustained QD sweeps. During the last ID36 test, the off replay and swapz prefill passed but swapz mixed timed out at its unchanged 280s bound. Under the intentionally exceeded cgroup `memory.high` limit, the Python mixed QD-wave dispatcher was still allocating a new `Future`/`WorkItem` per I/O, triggering avoidable reclaim throttling. Select the existing pre-created native-C QD32 waves for **ID36 only**, with identical immutable 128+2048 trace, byte-exact reads/writes, ownership, packed readback, CPU/memory pressure and original watchdogs. A kernel stall or wrong data must still BLOCK; native/CI checks do not prove the owner-loaded timeout is resolved. |
| 94 | Detached K=1 producer/ordered FIFO-head collision | **4 candidate / owner qualification pending** | The K=1 async lower pipeline reuses `lower_write_active`, but the producer's head-first rule predates detachment and assumes that signal means the ordered worker is blocked in synchronous lower I/O. During detached K=1 the ordered worker remains runnable, so a producer-owned PREPARING head can force a queue handback instead of useful inline LZ4 work. Distinguish the existing in-flight K=1 state: synchronous lower WRITE remains head-first; detached K=1 leaves a singular head for ordered steal and prepares true tails without idle credit. No new state, worker, buffer, lower depth, timer or format. Hypothesis: fewer preparation handoffs/waits and less preparing-head/no-ready idle, with equal or lower lower-WRITE work and improved fast mixed/QD4-QD32 service. Require exact-source owner `make test`, including raw/sync/async, p99, lower bytes/requests, lifecycle/fault/GC and SSE2/AVX2/AVX-512/NEON qualification. |
| 95 | Gate opportunistic RAW pressure selection on actual hand dispatchability | **4 candidate / owner qualification pending** | The retained close policy intentionally refuses the eight-record hand below a larger effective learned/sampled target, but ordered async preparation still forces records before that hand to RAW whenever eight accepted records are visible. That can spend lower bytes without starting I/O. Keep the qualified no-below-target dispatch rule; instead allow pressure RAW only when retention is disabled or the effective target is <= the eight-record hand. Larger-target waves retain LZ4 opportunity. Hypothesis: lower async backing WRITE bytes/requests and improve endurance proxy with neutral-to-positive useful service; risk is extra inline LZ4 CPU before larger targets on very fast media. Require exact-source owner `make test`, including raw/sync/async useful service, p99, lower bytes/requests, QD4/8/32, SD/SSD/NVMe, lifecycle/fault/GC and architecture qualification. |
| 96 | Retained suspend completion race against DM core barrier | **4 root-cause fix / owner requalification required** | Exact source `aaf2f523e3a8` passed build/native/W=1/W=2 plus loaded oracle, compound BIO, live GC and DISCARD/TRIM, then BLOCKED when the retained lifecycle writer failed after `dmsetup suspend` and `resume` both succeeded (report `522d1583447d`). The target closed admission in `->presuspend` and delayed buffered completions by 25–35ms hoping DM core would set `DMF_BLOCK_IO_FOR_SUSPEND` first. Linux DM converts ordinary-flush-suspend `DM_MAPIO_REQUEUE` to I/O error unless noflush/split/polled requeue rules apply, so the delay cannot prove safety. Move the existing closed-admission drain to `->postsuspend`, where DM has already blocked new I/O, crossed SRCU and waited for preexisting target I/O; remove delayed completion buffering. This is a lifecycle correctness repair, not ID94/ID95 performance evidence. Require exact-source owner `make test` before interpreting any benchmark. |
| 97 | Bounded accepted short-tail continuity at the work-conserving hand | **5 owner result did not justify keep / removed** | Exact source `b6461a8e2871` passed the full five-stage owner `make test`, but its latest report `e1eac4cd62b5` shows fast mixed async 33.62 MB/s, 2,816.2 lower-WRITE requests and 658.8 ms of undersized accepted-work lower idle. The older report had async 64.52 MB/s and 1,450.6 requests; synchronous throughput also moved sharply between runs, so the cross-report regression is not a clean causal A/B. The candidate nevertheless failed its promotion gate, and its unprepared pressure-hand claim can deliberately run ordered LZ4 before dispatching an already-serviceable batch. Remove that claim rather than retain an unqualified hot-path policy. |
| 98 | Retention-idle state repair after ID97 | **5 owner-qualified / partial keep; follow-up repair required** | Exact source `ffc527f4956b` passed the full five-stage owner `make test` and improved fast mixed async versus ID97 to 39.84 MB/s with 2458.0 lower-WRITE requests and 581.5 ms undersized accepted-work lower idle, but it still trails raw 62.81 MB/s and the earlier pre-ID97 64.52 MB/s baseline. Keep the READY-only pressure hand and correctness-side retained READ-bypass repair; preparation/ready-wait telemetry is zero on the failing workload, so do not add resources. The two-record/8KiB early latch and stale wave-level READ tail certification remain the bounded scheduling defects isolated by ID99. |
| 99 | Block-saving deferred pack and current-snapshot certification | **5 owner performance hypothesis rejected / geometry retained provisionally** | Source `de51b8e5` passed loaded `make test` but fast mixed useful WRITE fell from 39.84 to 35.14 MB/s while SERVICE_DRY/deadline fragmentation rose. Removing non-saving 2-record/8KiB latch improved sustained-write saturation, but does not establish a mixed win. |
| 100 | Bounded successful-READ continuity across continuing PACK chains | **5 owner result did not recover / superseded by ID101** | Exact source `6d0ea1225339` (report `41b2c14c5f8f`) passed all five stages but fast mixed async stayed at 38.42 vs raw 62.91 MB/s with 611.5 ms undersized accepted-work idle. The deadline itself, not READ-boundary bookkeeping, was the stall; see ID101. |
| 101 | Device-relative idle bound on the single retention timer | **4 owner-qualified (`0f5db1f`, report `08a4b85`)** | While a proven-dry staged window waits with no lower WRITE in flight, close at most half of one lower-WRITE service EWMA (20us floor, retain_ms cap) after idle began; never extend a deadline. Fast mixed -36% -> +8..+11% vs raw, SATA/NVMe mixed -66/-75% -> -50/-47%. Reopen only if owner SD/lifecycle evidence regresses. |
| 102 | Pure-WRITE half bursts wait for the learned width | **4 owner-qualified (`0f5db1f`)** | Under K=1 a pure-WRITE tail below the learned burst is the half staged during the previous run; merging beats ping-pong when the reissue gap is below the device's fixed latency and packs denser extents when bandwidth-bound. Fast QD8 -9% -> +21..+32%. Applying the same wait to mixed waves gave no SATA/NVMe gain and more idle-bound waits; mixed READ evidence keeps finite tails immediate. |
| 103 | Measured-cost RAW pressure hand | **4 owner-qualified (`0f5db1f`)** | Force RAW for an unprepared head only when per-page inline LZ4 exceeds half the per-block lower-WRITE service EWMA. On this host LZ4 is ~0.9 us/page, so QD8 stopped forcing 21% of records RAW (lower bytes 0.776 -> 0.747). |
| 104 | CPU-bound ordered workqueue | **4 owner-qualified (`0f5db1f`)** | The ordered owner now chains admission, K=1 completion and upper wakeups on the submitting CPU instead of waking idle remote CPUs: fast QD1 -12% -> -1.5%, QD4 -22% -> -12%, SD QD1 -4% -> -1%, ID36 pressure gate passes. Preparation stays unbound (ID7). `WQ_HIGHPRI` showed no effect and is not used. |
| 105 | `make fast_test` development loop | **1 owner-requested / keep** | One single-pair subset of the owned matrix (~85 s default) with a compact raw/swapz table and telemetry in `build/tests/fast-test/latest.json`. Never qualifies or publishes; `make test` remains the only qualification command. |
| 106 | Pressure-hand inline extension when LZ4 is cheap | **5 no effect / removed** | Hand closes on the NVMe trace happen when the accepted FIFO is genuinely dry, not over an unprepared queued head, so the gate never fired. |
| 107 | Unrelated READs stay independent after a K=1 window is dispatched | **1 owner-qualified (`03becc0`, report `b5227ca`)** | With an empty collector and an active run, a READ took the dependency path and its empty flush slept the ordered worker for the whole lower WRITE (traced ~127 us/wave in D state) while cache hits and stragglers queued. Committed mappings stay authoritative, so the in-flight run fence alone applies; window evidence and the deadline-after-READ flush still need an open window. SATA mixed swapz 188 -> 206 MB/s, READ p99 0.40 -> 0.24 ms. |
| 108 | Acknowledge a finalized run after the next window reaches the lane | **1 owner-qualified (`03becc0`, report `b5227ca`)** | Finalize delivered ~20 `bio_endio()` wakeups (1–5 us each, preempted by co-located writers) before dispatching the staged straggler window. Deferral (only with staged/queued work, preemption-disabled batch, delivered before any lower wait and before the work item returns) cut first-done -> second-issue from ~100 to ~17 us: SATA mixed 206 -> 216–223 MB/s; QD1/QD4 unchanged in interleaved A/B. A dedicated completion thread was not needed. |
| 109 | First window of a mixed wave waits for the learned width | **5 no throughput gain / removed** | Gating the first mixed window (chain_completed == 0) like ID102 cut SATA/NVMe lower requests 1047/1255 -> 868/1056 but left useful WRITE flat and raised idle-bound closes; under trace perturbation write p99 jumped to 2.3 ms. Stragglers arrive ~35–80 us late, close to what one fixed device latency saves. Reopen only with K=2 data showing merge beats overlap. |
| 110 | Fresh two-run lower-WRITE overlap after ID101/ID107/ID108 | **5 no demonstrated service benefit / removed** | ARM64 development experiment on `03becc0`/report head `b5227ca`, 2026-10-29: two disjoint immutable slots, FIFO publication, same-page append fences, bounded paused-group capacity and four-record successor service. Observed depth reached 2 on SATA/NVMe/fast mixed. Adjacent K=1/K=2 blocks, three `make fast_test` repeats each (mean useful WRITE MB/s): SATA 182.19/177.11, NVMe4 237.33/234.14, fast QD4 61.91/60.81, QD8 95.80/92.08, fast mixed 47.54/48.39. Lower-WRITE requests changed +21.2/+3.6/+0.3/+9.9/+3.9%; SATA lower-byte ratio 0.696/0.702 and fast mixed 0.762/0.765. Raw SATA 329.14/322.33 and NVMe4 422.61/439.16 show residual host drift; these pre-ID111 observations have no quiet-window screen and are directional, unpaired development evidence, not confidence-qualified regression claims. No demonstrated service gain repays the added requests, ownership state and buffers; restore K=1. Rootless, W=1/W=2, loaded smoke, full default development scenarios and ID36 passed. Reopen only with a materially different workload/policy and repeatable useful-service benefit without fragmentation; depth-two activity alone is insufficient. Authority blocker: swapz_authority keeps one paused batch group (batch_pending, batch_segment, batch_first_sequence and batch_hashes are singletons for one physical segment), so a second in-flight run needs a second paused group or segment with its own rollback and replay rules. |
| 111 | Compact automatic host-noise screen for development comparisons | **1 owner-requested / keep** | `make fast_test` adds 200ms pre/post quiet CPU/PSI/steal deltas, timed steal and >10% same-scenario raw-repeat spread checks. `NOISY`/`UNKNOWN` results set `performance_validity.performance_usable=false`, retain all evidence and print compact reasons. Timed workload CPU/PSI alone is never external-noise proof. Thresholds are conservative screening heuristics; `SCREENED` is not idle-host proof, single repeats cannot bound control drift, and owner `make test` qualification/ID36 is unchanged. |
| 112 | Per-round ARM64/NEON VM performance history plots | **1 owner-requested / keep** | After every optimization round, regenerate default-LZ4 mixed useful READ/WRITE, mixed p99, lower-WRITE savings and persistent-WRITE QD plots plus source-mapped CSV/JSON under `build/history/arm64-neon/`. Initial history through report `b5227ca` selects 51 owner-PASS NEON/seven-CPU reports from 230 revisions. Exclude failed/blocked/other-host and unqualified trial data; use each report's own raw controls and break kernel/model/content/replay discontinuities. Descriptive history never establishes causal gains or physical wear. |
| 113 | WRITE-folio locality as an equal-cost packing hint | **6 source audit / representative evidence gate** | See [reviewed measurement proposal](context.md). Current 4KiB splitting preserves page references but no explicit parent-BIO token. READ destination folios cannot identify earlier WRITE RAM; correlation needs bounded logical/generation tags and live-owner-only cohort discovery, with censoring and reuse handled explicitly. ID43 THP direct I/O is functional coverage, not real swap-locality evidence. Linux 7.0 block swap and newer `master` batching differ. Keep layout unchanged until folio membership predicts backing READ co-access beyond logical adjacency. A later policy must preserve full byte/read/extent costs and physical run/tail geometry; equal-length permutations are a narrower candidate than arbitrary reordering. No actual-swap collection or larger upper BIO is authorized by this design. |
| 114 | Focused K=1 critical-path profiling before another scheduler change | **2 passive instrumentation / ARM64 baseline collected** | Keep K=1, the four-record service rule, one preparation producer, the 64-slot reservoir, LZ4 acceleration one and SWZ unchanged. `make fast_test` defaults to three repeated SATA mixed, NVMe4 mixed, fast mixed, fast QD4 and fast QD8 pairs with existing host-noise screening. New interval telemetry measures accepted WRITE -> first ordered-worker ownership plus successful synchronous four-record wall/lower/non-I/O and completion -> next-four-record reissue gaps; existing counters supply ordered-worker CPU, accepted-idle unscheduled time, preparation/copy, ordering/planning, pack/CRC, lower service and publication. Detailed runs stay in `build/tests/fast-test/latest.json`; compact output is diagnostic. Choose at most one narrow production-C candidate from screened evidence, keep/remove it with matched `make fast_test`, refresh ARM64 history, then require exact-source `make test` for any retained change. |
| 115 | Delta64 rescue on by default | **1 owner decision / owner-qualified (`b86fefd`, report `0d97e99`)** | Owner decision after ID67: the transform is cheap and positive-content evidence is strong. Report `b5227ca` paired A/B on the delta64-positive fixture: compression ratio ~1.46 -> ~1.94, lower WRITE bytes -25%, useful WRITE +26% (+16..+35%), p99 -22%; transform 0.13–0.16 us/page on ARM64/NEON and LZ4 on transformed pages 4.6–5.0 vs 5.4–5.8 us/page untransformed. `delta64_rescue` defaults to 1 (0 disables) and `delta64_lz4_acceleration` defaults to 4, the second-pass value the A/B qualified (it was 1, an unqualified configuration, when rescue first became default-on). Standard mixed and write-only sessions run the default; the rescue A/B off arm and the medium-mixed envelope control pin `--no-delta64-rescue`; history plots key on the policy and break the line at the switch. Owner `make test` on `b86fefd` (report `0d97e99`; the earlier `de79f2e` run failed only on the ID114 profiling-epoch acknowledgement that `b86fefd` fixed) passed all five stages with standard sessions at rescue 1 / second-pass acceleration 4. Ordinary medium mixed content: the classifier scored every page, made 0 attempts and adopted 0, so lower bytes stay -25.8% (fast) / -30.5% (SD); its loaded wall is 81–155 ns/page in async mixed sessions (it takes the page's first cache misses). Fast mixed +10.8%, SD mixed +404%, fast QD1/4/8/32 -4.9/-11.3/+28.4/+50.0%, SD QD +0/+266/+252/+268%: unchanged within run-to-run noise versus rescue-off `b5227ca`. Paired positive A/B (off arm now pinned `--no-delta64-rescue`): useful WRITE +29.5% (+24.6..+34.3), lower bytes -25.0%, p99 -21.0%. Single directional delta-positive envelopes moved SATA 0.51->0.38 and NVMe Gen4 0.25->0.30; confirm before reading a trend. Revert only if representative content shows no prevalence or a matched service/CPU regression versus `delta64_rescue=0`. |
| 116 | NEON delta64 kernel shapes at -O2 | **1 keep inverse / ARM64 owner-qualified (`3362fa0`, `87180ee`)** | Development -O2 harness on ARM64/NEON (Apple core under VMware), pinned CPU, 15 interleaved rounds, byte-exact against scalar on 256 mixed-profile pages. Inverse: 16-word ZIP column scan 69–74 ns/page versus 85–88 ns for the per-vector EXT/DUP tree (~18%); 8-word ZIP 73–78 ns; LD4/ST4 columns 104–108 ns (slower). Forward: the existing EXT kernel stays (32 ns hot / 59 ns 1 MiB sweep); unaligned predecessor reloads 53/96 ns and a 128-byte unroll 32/61 ns did not help. Scalar is ~130–135 ns either way. The rootless suite builds at -O1, so its backend ns/page overstate kernel cost. Delta64 work is now ~0.1 us/page each way; LZ4 dominates the rescue path. |
| 117 | Byte-plane shuffle after delta64 before LZ4 | **1 owner-qualified: x86 `005592d`/`4886c4d`, ARM64 `3362fa0`/`87180ee`** | DELTA64_SHUF8 has record bits 15+14 and map bit 0x40; reject lone bit 14 and preserve plain DELTA64 decoding. Existing scratch and one SIMD section per combined call; one portable shuffle body per ISA. ARM64 native oracle/backend round trips, codec/map validation, rootless, W=1/W=2 and loaded smoke passed. Loaded delta-positive pair: rescue off 124.5 MB/s, 11.5 MB lower WRITE, p99 12.9 ms; shuffle on 298.1 MB/s, 3.05 MB, 0.98 ms, 1024 pages byte-exact. Prior plain-delta64 on arm was about 173 MB/s and 8.6 MB; this historical comparison is supporting, not a counterbalanced causal A/B. Offline delta-positive ratio 2.31 -> 6.81 and compression 3.25 -> 0.62 us/page; medium/entropy neutral, text/COW/raster can worsen, so retain classifier routing and existing adoption constraints. Owner x86 make test passed all five stages on 005592d (report 4886c4d), including scalar/SSE2/AVX2/AVX-512 runtime checks. Synthetic profiles do not establish population prevalence. |
| 118 | Preemption-disabled ACK batch for successful synchronous four-record windows | **5 no measured benefit / removed** | On `005592d`, three screened fast QD4 repeats: original 73.79 vs candidate 73.81 MB/s, reissue gap 39.58 vs 39.52 us. Lower bytes stay 0.750 of raw. Existing deferred K=1 ACK batching (ID108) remains; applying it to this synchronous path did not repay a new branch. Reopen only with a demonstrated reissue/wakeup improvement. |
| 119 | Queue ordinary retained WRITE wakeups instead of modifying pending immediate work | **5 no repeatable service gain / removed** | Same-source ARM64 development: initial QD4 +1.1%, but adjacent five-repeat candidate/control blocks give 74.12/74.65 MB/s with raw 84.06/84.01; SATA 231.72/228.93 with raw 395.38/395.49. Candidate NVMe blocks fail the >10% raw-spread screen. A small SATA-only observation does not justify changing wake semantics. Preserve accepted-idle wake timestamps in any future queue experiment; no selector/alternate path retained. |
| 120 | IRQ-masked groups of four deferred acknowledgements | **5 inconclusive / removed** | Five screened SATA repeats 231.54 vs adjacent original block 228.93 MB/s; raw 392.86 vs 395.49. Fast mixed stays about 69.8 MB/s, within observed variation; NVMe excluded for raw spread. Diagnostic perf samples cluster at completion IRQ-restore return and can skid from masked intervals, so they cannot prove precise completion CPU cost or justify longer masking. Keep original IRQ behavior; require repeatable useful-service and latency benefit before reopening. |
| 121 | Let adjacent READ coalescing scan across disjoint queued retained WRITEs | **5 no demonstrated opportunity / removed** | ARM64 on `005592d`: the standard mixed timed interval has only nine lower READ requests, with almost all READs cache-resident and zero asynchronous READ batches. Extending the bounded prefix gives SATA 221.54 -> 222.52 MB/s and fast mixed 69.26 -> 69.34, within variation; NVMe noisy. A private C prototype covers queued same-page hazards, fences and 64-record bounds, but no new policy ships. Reopen only on a measured cold/mixed-read workload with real adjacent missing ranges. |
| 122 | Reject cached FIFO heads before independent READ fan-out scans | **5 not promoted / removed** | Before the quantum repair, adjacent candidate/control/candidate blocks show SATA 230.22/228.36/232.49 MB/s, worker CPU 29.40/31.37/29.08 ms and READ p99 0.237/0.288/0.241 ms. With corrected worker accounting, the combined trial gives SATA 212.14 versus 220.66 for accounting alone, and fast mixed 67.74 versus 69.47; lower requests/arrival geometry also vary. CPU savings alone do not establish a useful-service win. Remove the shortcut and its test/policy branch; reopen only against the corrected budget baseline with repeatable service/latency evidence. |
| 123 | Restore the finite worker BIO quantum after rejected READ probes | **1 owner-qualified ARM64 (`b30b2ab`, `8458690`)** | The coalescing probe clears `processed_out` even on false; the worker previously retained zero for an ordinary BIO, so its 64-BIO budget did not decrement and its reschedule predicate could fire per BIO. Restore the ordinary one-BIO charge after both probes decline, preserving accepted batch counts, and skip READ probes for non-READ heads. An executable extraction of the real selection block fails on the old source and passes for zero/poisoned rejected counts, successful 5/3-BIO batches, non-READ bypass and exactly 64 fallback completions. Rootless and development byte-exact replays pass; exact source b30b2ab then passed all five official stages (report 8458690), including resource pressure. This is a fairness/accounting repair; throughput impact is mixed and no speedup is claimed. |
| 124 | Reissue-gap decomposition at barrier-wave boundaries | **2 passive measurement / keep as diagnostic** | Traced `make fast_test` on `b30b2ab`, one run per device; tracing slowed swapz about 6% on SATA and 17% on NVMe, so absolute microseconds are inflated. Upper arrivals grouped in 32-op blocks; all 512 SATA blocks hold exactly 32 completions. SATA: writer arrival spread 98 us p50; the fourth write arrives 11 us into the block, but the first lower write issues 61 us after the first arrival (24 of 503 blocks dispatch within 10 us of the fourth arrival); inter-window gaps 17 us p50 with all records already staged (7 of 514 gaps had arrivals inside); last completion to last ack 40 us; device idle 26% of the active span. NVMe, 409 blocks: spread 117 us, first window 70 us after first arrival, gaps 85 us per block (36% of gaps had arrivals inside, median 65 us), device idle 56%. Ordered-worker CPU 2.5 us per op on SATA and 3.0 us on NVMe, on-CPU about half of its active wall; cached reads cost about 1.1 us and writes about 1.2 us on the worker. |
| 125 | Idle lane never holds a pure-WRITE tail below learned width | **5 refuted / removed** | Hypothesis from row 124 that the first-window hold is the ID102 pure-WRITE rule. Development-only variant, not committed, `make fast_test` REPEAT=2 against the b30b2ab baseline means: SATA 226.1 vs 231.5 MB/s, NVMe 339.6 vs 349.0, fast mixed 69.6 vs 70.0, fast QD8 82.6 vs 105.6 (-22%, the ID102 ping-pong regression). The first-window hold is not this rule. |
| 126 | Idle lane closes a window at four staged records despite queued followups | **5 no demonstrated gain / removed** | Development-only variant, not committed, REPEAT=2 against the same baseline: SATA 239.2 vs 231.5 MB/s (baseline range 228.9-233.2; two repeats only), NVMe 349.1 vs 349.0 with lower-write requests about 17% higher (1,470-1,479 vs about 1,250), fast mixed 69.4 vs 70.0, fast QD8 105.4 vs 105.6. Lower bytes unchanged, so endurance does not improve and request count rises. Not promoted. |
| 127 | Idle-bound hold at full rather than half lower-WRITE service | **5 refuted / removed** | Development-only variant, with the native window-policy expectations matched for the run and restored afterwards; `make fast_test` REPEAT=2 against the b30b2ab baseline means: SATA 217.9 vs 231.5 MB/s (-6%), NVMe 336.5 vs 349.0 (-4%), fast mixed 66.8 vs 70.0 (-5%), fast QD8 108.0 vs 105.6 (+2%). Idle-bound closes fell from about 129-153 to 115-123 per run, but the longer hold cost more device idle than the saved window boundaries recovered. Byte and request counts unchanged. The half-service bound from ID101 stays. |
| 128 | Ordered workqueue unbound instead of bound to the submitting CPU | **5 refuted / removed** | Development-only variant, restored afterwards; `make fast_test` REPEAT=2 against the b30b2ab baseline means: SATA 223.8 vs 231.5 MB/s (-3%), NVMe 329.5 vs 349.0 (-6%), fast mixed 69.0 vs 70.0 (-1%), fast QD8 110.8 vs 105.6 (+5%), fast QD1 19.1 MB/s against about 21 in earlier runs (-14%, the ID104 regression). Lower-write requests fell about 11% on SATA and 19% on NVMe with bytes unchanged, but mixed throughput did not improve. The bound worker from ID104 stays. |
| 129 | Fan out independent RAW READs through the existing eight slots | **1 owner-qualified ARM64 (`a9bfe44`, `1e8a5bb`)** | Standard medium timed READs mostly hit cache and cannot measure RAW fallback. All-entropy development control issues 4,083 lower READs and zero async batches: SATA 72, NVMe4 168, fast 42 MB/s useful WRITE. Extend only existing private READ slots to authoritative one-block RAW, retaining staged/in-flight/queued-WRITE/fence checks, lower-callback ownership and CRC verification; never prime/seed/absorb RAW in SWZ caches. No new worker, buffer, RAW cache or WRITE depth. Ten prospective counterbalanced source rounds, ten declared model/content endpoints, SCREENED/provenance-matched pairs and <=10% paired raw drift; exclude noisy/missing pairs without replacements. Require exact two-sided sign p <=0.005 (Bonferroni family 0.05), 99.5% paired log-effect t intervals and a +3% practical floor. Balanced content: SATA +41.4% [37.9,45.0], NVMe4 +23.9% [20.6,27.2], fast +13.5% [11.9,15.2], all n=10/p=0.001953. Entropy SATA +116.5% [108.3,125.1], n=9/p=0.003906; fast +43.5% [39.0,48.2], n=10/p=0.001953. Entropy NVMe4 +60.0% remains inconclusive at n=8/p=0.007812 despite its positive interval. Medium SATA/NVMe4/NVMe5/fast changes remain inconclusive; their intervals do not prove equivalence or exclude every small regression. Source control uses b30b2ab production C; dirty source hashes, complete excluded-pair reasons and secondary metrics are archived under build/optimization-round/raw-trial/paired. Balanced fast lower WRITE bytes +0.2% and requests +5.1% are trade-offs, not endurance improvements; balanced SATA/NVMe4 byte changes are unresolved. Rootless extracted target-C/real-CRC tests and W=1/W=2 pass. Exact source a9bfe44 passed all five official stages (report 1e8a5bb), including the mandatory all-RAW/balanced gate: 2,048 verified pages, 172 async READ batches, 768 lower READ requests. Current-source x86 loaded qualification remains outstanding. |
| 130 | Prepare accepted WRITE heads while the owner joins RAW READs | **5 no demonstrated material service gain / removed** | Fresh aggregate probe on a9bfe44 C: balanced SATA/NVMe4/fast has 379/368/206 eligible RAW groups with no lower WRITE active, mean unclaimed WRITE backlog 15.5/14.2/6.4, and join wall 134.8/39.9/174.2 us; producers inactive at 359/346/200 starts. This is a real opportunity, unlike the old cached medium workload, but it is not a performance win. Trial lends heads to the existing one producer only for RAW submit/join intervals with >=4 queued WRITEs, preserving snapshot ownership and clearing the flag before decode/WRITE processing. Producer head claims rise into thousands. Ten prospective counterbalanced source pairs on three balanced targets use SCREENED/provenance/raw-drift exclusions without replacements, exact sign cutoff 0.05/3 and 98.333% paired log-effect t intervals, with a predeclared +3% practical floor. SATA n8 +1.77% [0.44,3.11], p0.0703; NVMe4 n10 +2.39% [0.23,4.58], p0.1094: fail the exact-test criterion. Fast n10 +1.35% [0.83,1.88], p0.001953: detectable but below the practical floor. Secondary request point estimates rise ~6–9%; no endurance improvement is established. Remove all probe counters/logging, flag, helpers and scheduling changes; kernel C remains byte-identical to qualified a9bfe44. Patches/data remain local under build/optimization-round/read-prep. Reopen only with a distinct mechanism addressing request fragmentation or a new demonstrated material service opportunity. |
| 131 | Correct worker-CPU diagnostic scope | **1 reporting clarification / no timing or policy change** | Existing cheap boundary reads of current->se.sum_exec_runtime can omit pending execution and can include pre-entry execution when accounting updates inside a callback. They are neither exact callback CPU nor guaranteed lower bounds. Explicit phase timers measure partial wall time and can include involuntary preemption. Correct fast-test labels, structured cpu_scope and standards; retain existing metric names/values for compatibility and preserve the ban on unexported scheduler helpers. Do not infer CPU savings from the ID130 work transfer. This changes interpretation, not product service or qualification gates. |
| 132 | Replace shared-pool owner dispatch with one private kernel-thread worker | **5 unpromising development pilot / removed** | Existing medium traces show several milliseconds of wake-to-entry and lower-completion-to-finalization wall time, with overlap possible. Prototype replaces only the serialized owner work item with one kthread_worker, preserving FIFO, quantum, preparation producer, lower WRITE depth and publication ownership; no affinity or spin wait. Exported queue/flush/cancel APIs and lifecycle semantics inspected; final producer join precedes final owner flush and producers stop before their post destination is destroyed. Declared control-before / candidate / control-after pilot, three repeats each, uses medium SATA/NVMe4/NVMe5/fast mixed and fast WRITE QD1/4/8. Every replay/image check passes. Fast raw controls remain near 22/84 MB/s at QD1/4, while swapz pilot means are 21.85/74.76 before, 19.40/67.24 candidate and 21.17/74.49 after. These are descriptive pilot observations, not statistically qualified regressions. NVMe raw variation and excluded SATA/NVMe observations prevent causal interpretation of small mixed-workload differences. No material broadly useful signal justifies a prospective confirmation or added lifecycle complexity. All kernel changes removed; C remains byte-identical to qualified a9bfe44. Local source hashes, screen exclusions, logs and plotted samples remain under build/optimization-round/owner-task. Reopen only with new evidence isolating a material owner-dispatch bottleneck. |
| 133 | Classify proven-dry timer parks by size, RAW content and mixed READ proof | **1 passive question answered / probe removed** | On qualified a9bfe44 C, append-only aggregate probe records park-to-next-owner-entry wall time at dry, lower-idle timer returns. Status snapshots allow exact timed subtraction by verified logical WRITE/READ byte deltas. Twelve development cases: medium SATA/NVMe4/NVMe5/fast mixed plus fast QD4/QD8, and balanced/entropy SATA/NVMe4/fast mixed. Zero >=4-record mixed parks in every case: current service_close_ready already authorizes the four-record lower-idle hand regardless of compressed-pack geometry, so the old all-RAW dry-tail gap hypothesis is stale. Timed mixed 1–3-record park wall: medium 8.42/8.51/7.60/49.92 ms, balanced 2.55/2.46/21.56 ms, entropy 0.18/0.40/1.76 ms. Larger parks belong to protected pure-WRITE bursts. This is instrumented wall attribution, not a performance A/B or permission to reopen rejected singleton/pure-tail cutoffs. All counters/logging removed; data local under build/optimization-round/dry-park. |
| 134 | Coalesce ordinary retained WRITE owner kicks on a nonempty incoming FIFO | **5 unpromising development pilot / removed** | Unlike ID119, skip the workqueue call entirely for an ordinary retained WRITE if older incoming work already owns progress; preserve empty-transition, READ/fence/nonretained, lower completion, READY/error and finite-worker requeue wakes under queue_lock. Declared control/candidate/control pilot, three repeats on seven medium scenarios; all replay/image checks pass. SATA useful WRITE means 210.07/218.02/219.34 MB/s: final control reproduces the apparent gain. Fast mixed 67.93/68.58/68.56; QD4 71.78/72.57/72.18; NVMe4 352.41/344.40/348.83; NVMe5 358.81/356.64/357.17. No statistically qualified gain/loss conclusion or promotion from these pilot means. Remove the branch; C stays a9bfe44. Source hashes, full QD1/8 results and exclusions local under build/optimization-round/admission-kicks. |
| 135 | Suppress detached preparation wakes below the existing two-descriptor claim minimum | **5 unpromising development pilot / removed** | ID136 phase probe motivates matching common kick eligibility to the producer's protected-head rule: when K=1 is detached and only one unclaimed descriptor exists, skip that kick; preserve synchronous lower-WRITE head preparation at any depth, existing owner/result wakes and all representation ownership. Three-repeat control/candidate/control on medium SATA/NVMe5/fast mixed and fast QD4/QD8; every replay/image check passes. SATA 217.52/218.29/218.43 MB/s, fast mixed 68.29/67.87/68.00, QD4 71.59/72.24/72.55; candidate NVMe5 excluded by raw-repeat drift. QD8 102.69/108.23/105.98 remains a pilot observation, not a significant win. No demonstrated material service advantage justifies retention. All changes removed; data/source hashes local under build/optimization-round/producer-eligibility. |
| 136 | Attribute admission queue-lock wall phases without treating sampled return PCs as CPU | **1 passive question answered / probes removed** | Initial perf capture lacks symbols for modules loaded after recording starts and cannot support target function costs. Live-module capture resolves 1,423 swapz-containing stacks, but 330/339 map leaf samples land at +0x268 after IRQ restore; software-clock skid prevents precise function CPU allocation. VM has no supported cycles/instructions PMU. Separate C phase clocks, matched to timed snapshots, show mean ordinary WRITE setup/wait/hold/owner-kick ns: SATA 58/773/753/344, NVMe4 59/644/702/330, NVMe5 53/714/669/330, fast mixed 57/58/2336/445. Producer queue calls occupy ~22.1 ms of fast mixed lock hold, versus total WRITE lock hold 9.26/8.64/8.22/28.73 ms across those targets. Extra clocks/counters perturb execution and wall includes scheduling/VM effects; do not call these CPU totals or causal service savings. IDs134/135 test two narrow implications and are removed. No probe or timing code ships. Local artifacts: build/optimization-round/admission-cost and cpu-profile. |
| 137 | Hybrid sleep-then-spin wait for short detached lower WRITEs | **5 unpromising development pilot / removed** | Development-only variant on `19c061f` (production C = `a9bfe44`), restored afterwards. After each worker pass, while a detached lower WRITE with service EWMA <= 200 us is in flight, the worker sleeps with usleep_range until 20 us before its expected completion, then spins on completion_done() (exit on new incoming work or at 1.25x EWMA) and runs the next pass itself, at most 16 extra passes. Detached finalization records no blocking wait (pipeline_finalize_wait_wall_ns = 0); this does not prove every window is detached: the saved sessions also contain synchronous four-record windows. The targeted wake is detached completion -> worker entry. `make fast_test` REPEAT=2, adjacent baseline/variant means: SATA mixed 230.8/216.7 MB/s (-6%), NVMe4 mixed 350.2/321.4 (-8%, lower WRITE requests +9%), fast mixed 70.0/70.4, fast QD4 74.2/75.0, fast QD8 107.6/109.1. The separately measured synchronous four-record reissue gap changes SATA 144.7 -> 111.1 us and NVMe4 98.8 -> 26.7 us; it is not a direct measurement of the targeted detached wake. The cheap ordered-worker scheduler diagnostic rose from 29-31 to 40-44 ms on SATA and 41-44 to 52-54 ms on NVMe4; ID131 explains why this is not exact callback CPU. SATA accepted-WRITE -> worker ownership rose 24.6 -> 50.7 us. The bound worker (ID104) can compete with its submitters while spinning. These two-repeat means do not establish a statistically significant regression or isolate its cause; they provide no material service signal supporting retention. Reopen only with a distinct CPU/service hypothesis. |
| 138 | Post admission notifications after queue unlock | **5 unpromising development pilot / removed** | Candidate snapshots wake decisions before publishing the BIO, then moves preparation/owner notifications outside queue_lock with a preemption guard. It never dereferences the BIO after unlock; target lifetime is protected through map return by DM table SRCU. Direct destruction can start drain earlier, so this is not a general drain-before-map-return guarantee. Declared control/candidate/control, three repeats on seven medium scenarios: SATA 224.38/229.88/228.47 MB/s, NVMe4 344.25/346.17/350.67, NVMe5 363.48/366.43/365.63, fast mixed 69.45/67.42/69.31, QD4 74.09/74.74/74.26. Every byte oracle passes; means do not demonstrate a significant material gain. Remove changes; kernel C remains a9bfe44. Source/logs local under build/optimization-round/admission-unlock. A subsequently inherited notification variant without the guard had an interrupted run, not completed qualification, and is archived separately under window-lead. |
| 139 | Separate sparse null_blk RAM first-touch from target cost | **1 diagnostic answered / no protocol promotion** | Transfer-scoped allocation tracing confirms fresh RAM backing allocates on first writes; counts cover the full pair and are not timed-phase CPU attribution. Prewarming both newly owned 64MiB devices before timing changes the backend for both arms, not product C. An attractive pilot fails prospective confirmation: 12 fixed counterbalanced pairs on three medium targets, primary paired log effect of (swapz/raw) prewarmed versus standard, 98.333% intervals, exact sign cutoff 0.05/3 and +3% practical floor. SATA n12 +1.31% [-0.67,+3.33], p0.146; NVMe5 n11 -0.58% [-5.53,+4.63], p1; fast n11 +0.73% [-0.24,+1.70], p0.549. One NVMe5 and one fast pair excluded by predeclared screens, no replacements. All inconclusive, not equivalence. No cross-protocol raw-drift exclusion because raw is also affected by preconditioning. Restore the helper/recorder; no production change or historical performance point. Local full evidence and plot: build/optimization-round/null-first-touch/paired. |
| 140 | Decompose fourth-admitted WRITE to first physical lower issue | **1 passive question answered / probe removed** | Bounded preallocated 8192-event prefix per target, original queue locking, ordered-compression/ready/flush/lower-API events, block issue/completion and owner scheduling. Reject the first incomplete dump; final indices are contiguous and wave BIO ownership balances. On 1edf76f/a9bfe44 C, SATA has 21 complete eligible waves; NVMe5 has 20 plus one first window of three. Mean lead partitions (us), admission-to-ownership / fourth representation / service after fourth ready / plan-pack-reserve / lower API-to-issue: SATA 9.07/2.09/50.97/4.00/2.31; NVMe5 9.65/1.86/40.10/4.39/1.92. Owner scheduled callback wall 54.11/53.67 us includes ~13 us ordered compression and ~5/6 us lock acquisition; blocked means 12.49/2.86 us mostly coincide with lower READ service. Scheduled wall includes IRQs, not exact CPU. First-window median 16/12 records; complete waves use 1-3/1-4 lower windows. Service after four includes later accepted work, not pure waiting. Earlier dispatch may add serialized requests (ID126); summed concurrent lock waits cannot be subtracted from wave wall. No causal gain/loss claim. Remove all probe C; source remains a9bfe44. Local trace, analysis and plot: build/optimization-round/window-lead. |
| 141 | Isolate mixed-workload wave barriers with identical lane-owned streams | **1 workload sensitivity measured / development controls retained** | Persistent mixed lanes and a matched lane-owned wave control leave the official mixed workload intact. Both modes have identical trace/payload/final-image hashes: each lane owns its WRITE stripe, READs use immutable disjoint pages, pre-created native C workers differ only in barrier selection. Twelve prospectively fixed rounds rotate model order and alternate mode order; all 36 pairs are SCREENED and byte/hash exact, no exclusions/replacements. Primary paired log change of swapz/raw useful WRITE ratio, 98.333% intervals and exact sign cutoff 0.05/3: SATA +85.38% [71.74,100.11], NVMe5 -49.79% [-51.87,-47.61], both material; fast +1.98% [0.93,3.05], detectable direction but +3% materiality unresolved. All sign p=0.0004883. Descriptive mean raw/swapz MB/s, waves -> persistent: SATA 388.5/221.1 -> 408.6/430.9; NVMe5 616.8/372.7 -> 1948.2/590.5; fast 63.0/121.1 -> 63.0/123.5. These do not separately qualify swapz-over-raw significance. NVMe accepted-idle selected-wait total falls 26.27 -> 1.41 ms, while its separate accepted post-lower interval rises 4.32 -> 16.18 ms; neither is a complete device-idle budget. Deferred-ACK wall 23.18 -> 32.76 ms includes preemption at preempt_enable, not exact CPU. Removing barriers helps absolute swapz service but exposes a larger NVMe raw gap; it does not explain that gap away. Raw is first within each owned pair; workload intervention affects both arms, so cross-mode raw changes are outcomes, not exclusion criteria. Keep replay identities separate; do not merge into old history or infer a source speedup/real-swap result. Production C remains a9bfe44; local plan, hashes, logs, intervals and plot: build/optimization-round/mixed-lanes. |
| 142 | Split ACK-loop, enable-return and lower-done handoff wall | **1 passive question answered / probe removed** | On 1e96108/a9bfe44 C, preallocated bounded C events plus scheduler switches capture all 16,384 timed operations in persistent NVMe5 and a matched wave control. Both complete with exact bytes, contiguous event indices and no reported trace loss. Persistent ACK loop 36.09 ms, enable-to-return 0.147 ms; wave 27.10/0.478 ms. No owner off-CPU interval overlaps the ACK loops, but IRQ execution remains included: do not call loop wall exact CPU. Persistent lower-done-to-finalization-start 16.12 ms, of which 12.67 ms overlaps delivery of the preceding ACK cohort; wave 11.16/7.24 ms. Only 0.10 ms of persistent post-lower delay is owner-runnable off-CPU, versus 15.55 ms scheduled callback wall. This contradicts the hypothesis that the ~33 ms ACK timer was mostly a preempt_enable scheduling artifact and motivates moving completion work rather than another wake/spin trial. Remove all probe C. Exact logs, interval analysis and plot local under build/optimization-round/completion-handoff. |
| 143 | One bounded published-ACK batch on the existing unbound preparation queue | **1 ARM64 owner-qualified (`d2b66ac`, `77a0c3c`) / throughput-I/O trade-off** | After serialized lower-success publication and prepared-slot release, transfer one 4..64-BIO cohort only while a new detached lower WRITE is pending. Single atomic slot, existing queue/producer width, inline fallback while occupied; queue publication is serialized with admission close under queue_lock and drain joins all completion work. Preserve preemption-disabled delivery and atomic completion/DM-endio counters. No early ACK, second lower run, I/O buffer or helper authority mutation. Final C exactly matches owner-qualified d2b66ac. A separate fixed 16-round final-source confirmation on four medium workloads uses six prespecified service/I/O endpoints, SCREENED/provenance/<=10% paired raw-drift exclusions without replacement, 99.1667% paired log-effect intervals and exact sign cutoff 0.05/6. Persistent NVMe5 n13 useful WRITE/raw +22.66% [18.47,27.00], p0.000244; mean raw/swapz control 2023/572 and candidate 2051/712 MB/s. Lower WRITE bytes +1.29% [1.13,1.46] and requests +26.22% [22.66,29.88], both p0.000244: an explicit throughput/I/O trade-off, not an endurance improvement over control. Candidate still writes ~29.7% fewer bytes and ~90.4% fewer requests than raw. Legacy NVMe5 n16 +4.45% [1.67,7.31], p0.00418: detectable positive direction but +3% materiality unproved; SATA n16 +0.35% [-0.03,0.74] and fast n16 +0.12% [-1.16,1.42] inconclusive around zero. All legacy -3% guards pass; three persistent pairs excluded, no legacy exclusions. These bounds do not prove exact equivalence, raw parity or gains on other content/hosts. READ/WRITE p99 are secondary; no total CPU reduction is established. Final-source hashes, prospective plan, all observations and plots: build/optimization-round/completion-handoff/paired-final; earlier prototype/pilots remain local separately. All five owner stages pass, including actual target-body native tests, 602 handoffs/16,512 exact WRITEs across suspend, seven handoffs before lower failure with post-failure EIO, and ID36. Current-source x86 qualification remains outstanding. |
| 144 | Observe admission/completion CPU locality before choosing another ACK mechanism | **1 passive association measured / probe removed** | Three byte-exact instrumented sessions on qualified d2b66ac C: NVMe5 persistent, matched waves and fast WRITE QD4. Preallocated bounded events have contiguous indices and capture all 16,384/16,384/4,096 timed operations with paired endio entry/return. Median READ endio wall, different/same admission CPU: persistent 2.584/0.500 us, waves 3.250/0.708 us; fast QD4 owner WRITE 2.708/1.250 us. IRQ/off-CPU observations do not make the remainder exact CPU. Placement and probe overhead confound these conditional associations; no causal gain, removable budget or significance claim. Globally sort per-CPU BPF records before correlation. Reject the raw request-locality comparison: native GO-to-fsync has 12,301 issue events per run but only 11,438/11,945 matched completions, with duplicate keys and pending requests despite no reported ring loss. No raw CPU-locality inference survives that completeness failure. Probe and capture buffers removed; qualified production C unchanged. Local event traces, completeness analysis and plot: build/optimization-round/completion-locality. |
| 145 | Separate helper completion atomics from owner statistics | **1 unpromising layout pilot / padding removed** | DWARF puts helper-updated completion/DM-endio atomics at offsets 23936..23968 and owner READ/WRITE statistics from 23976 in the qualified context. Hypothesis: possible coherence cost, not proven false sharing. Align both group boundaries to twice SMP_CACHE_BYTES (128 here); compiled owner stats move to 24064 and context size 24832 -> 24960 bytes. Physical host cache-line size is not established. Fixed control-before/candidate/control-after, three medium repeats on eight scenarios, same fixtures/traces/oracles and DELTA64=1. All 72 pairs are byte-exact; NVMe4, fast mixed and persistent NVMe5 lack a complete usable three-block comparison due declared raw-repeat screening. Remaining descriptive candidate changes in swapz/raw WRITE ratio vs before/after: SATA +2.24/+7.93%, NVMe5 waves -4.64/-2.15%, fast QD1 +1.04/+0.22%, QD4 +1.20/+5.14%, QD8 +1.77/+6.83%. Unpaired short blocks do not establish significance, equivalence or causal cache effects. No sufficiently persuasive repeatable pilot signal to retain padding or fund confirmation; remove it without claiming a statistically established regression. Exact qualified d2b66ac C restored. Local source hashes, compiled layouts, all observations and analysis: build/optimization-round/completion-counter-layout. |

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

ID43 already qualifies 4KiB slices backed by THP/compound memory. ID113's
[folio-locality audit](context.md) separates that completed input-shape
support from unqualified semantic locality and larger upper-BIO admission.
The current upper READ/WRITE contract remains exactly 4KiB.

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


## MM-aware storage blueprint: zswap collaboration and locality

**Direction.** Preserve swapz's independently decodable 4KiB logical records
and 4/8/16KiB SWZ physical extents while avoiding wasteful compression work
when the Linux swap path already compressed a page. Combine that with
no-wait locality-aware placement only when it does not sacrifice bytes,
bounded cold-read cost, extent count or lower-device service. The technical
explanation of Linux reclaim, folios, BIOs and the zswap writeback implementation
lives in [context.md](context.md), not in this rolling blueprint.

**Scope and priority.** This is planned cross-subsystem work, **not an enabled
feature or evidence of a current performance win**. Keep the current near-term
work-conserving four-record service effort and owner qualification ahead of
this integration. Current host safety still forbids `swapon`/`swapoff`;
none of the following authorizes actual kernel swap tests, physical devices,
new public test commands or an SWZ format change. Move the actual-swap portion
only after explicit owner authorization and the relevant safety design.

### Goal, measurable hypothesis and non-goals

The specific zswap case is **stored-then-evicted writeback**: zswap may
compress a page into RAM, later decompress it into a normal swap-cache folio,
and pass that page to the backing device. Today swapz can recompress those
bytes. An explicit origin hint could allow the swapz dispatcher to bypass its
own compression, reduce accepted-work lower-idle time and save CPU/wakeups,
possibly at the cost of more lower WRITE blocks and future cold-read traffic.

The first experiment asks whether the saved compression and scheduling time
outweighs the extra physical service time **on each target device class**.
Do not assume that the answer is identical for fast NVMe, SATA and SD/slow
backing. Do not infer origin from `REQ_SWAP`, a PID/current task, folio
drop-behind, a zswap presence check, or a failed `zswap_store()`.
Object-aware extents, direct interpretation of zswap bytes as SWZ LZ4,
additional producer lanes/buffers and an SWZ format extension are not part
of the initial feature.

### Phase A — establish an explicit and testable origin contract

1. Reinspect the target Linux version's `mm/page_io.c`,
   `mm/zswap.c` and Device Mapper BIO cloning/splitting path; record exact
   origin propagation sites and lifetime requirements. Upstream reference
   anchors are in [context.md](context.md).
2. Define a narrowly scoped semantic origin, at minimum
   `ORDINARY_OR_UNKNOWN` versus `ZSWAP_STORED_WRITEBACK`. Distinguish
   `ZSWAP_INITIAL_REJECT` only if the kernel explicitly supplies it;
   rejection alone does not imply incompressibility.
3. Carry the origin from `zswap_writeback_entry()` through
   `swap_io_ctx` / backing-BIO creation to the swapz per-BIO descriptor.
   Choose a reviewed explicit kernel/BIO interface; a hypothetical
   `REQ_ZSWAP_WRITEBACK` is **not** currently a real flag or committed ABI.
   Preserve origin during BIO split/clone, and prevent mixed-origin folios
   from being mislabeled by a single whole-BIO tag.
4. Preserve unknown/non-zswap traffic exactly as today. Kernel builds
   without the new origin interface must compile with unchanged behavior,
   without guessing from a shared flag. Document any kernel-version guard
   only where required by the actual implementation.

**A exit gate:** source/native contract fixtures can manufacture ordinary,
reject/unknown and verified zswap-writeback origins and prove correct routing
through a split/clone-equivalent path; ambiguous origin never triggers
compression bypass. No change to authority or on-media format.

### Phase B — first no-recompression representation candidate

1. On a correctly tagged write, skip **both** ordinary LZ4 and delta64
   work, including unnecessary producer-queue claims and compressed-result
   allocation. The existing `struct swapz_bio_ref` has
   `preparation_force_raw`, and `swapz_accept_write()` has a forced-RAW
   route, but these are presently scheduling-specific: setting that bit
   in `swapz_map()` alone is **not** a complete implementation.
2. Coordinate admission, the bounded preparation queue and any already
   claimed producer slot so the descriptor gets a **stable 4KiB RAW
   snapshot** and one terminal representation selection before it can be
   sealed. A producer must not read a BIO after upper completion; an
   asynchronous result must not overwrite a selected RAW representation.
   Avoid waiting for a worker that was intentionally bypassed.
3. Use existing RAW placement, mapping/generation/CRC and serialized
   authority publication after definitive lower-I/O completion. Preserve
   one upper-BIO completion, zero-page exactness, fences, duplicate-page
   ordering, DISCARD, GC, suspend, teardown, failure and rollback rules.
   Unsupported/unavailable RAW batching must safely fall back to existing
   semantics instead of silently dropping or reinterpreting the write.
4. Maintain the work-conserving dispatcher: dispatch the best available
   representation from already accepted writes at the current service hand.
   Do not delay lower service for better compression, future folio partners
   or a fuller window.

**B exit gate:** exact byte readback, full authority/lifecycle/native
regressions, no leaked prepared slots and zero swapz LZ4/delta64 attempts on
**tagged RAW-bypass** writes. Unknown/ordinary writes retain current
compression behavior; independently measured lower bytes/requests remain
visible rather than hidden behind a throughput claim.

### Phase C — evidence and storage-adaptive selection

Compare **matched zswap-enabled** workloads with the explicit-origin hint
disabled versus enabled, including genuine stored-then-evicted zswap pages,
ordinary backing writes and initial zswap rejections. Keep useful work,
compressibility, device/queue depth, zswap compressor/pool and fault behavior
equivalent. Record at least:

- zswap accepted/rejected/evicted backing pages and reliable tagged counts;
- swapz tagged pages selecting RAW and attempted compression (must be zero);
- zswap decompression time and swapz compression CPU/wall saved, prep-slot
  occupancy, accepted-work lower-idle time and lower active fraction;
- useful WRITE and READ throughput, p95/p99 latency, CPU/RAM footprint;
- independently measured lower READ/WRITE bytes and requests, plus GC,
  overwrite, DISCARD and subsequent swap-in/read amplification.

Use the existing representative fast, SATA/NVMe, slow/SD, and QD1/QD4/QD8/QD32
evaluation dimensions where available. A faster write with materially more
lower traffic is a **device-dependent tradeoff**, not proof of product success.
A slow device may prefer recompression; fast storage may favor immediate RAW.
Only introduce a device-sensitive choice if measurements exclude a simpler,
work-conserving default, and retain bounded/atomic representation ownership.

**C exit gate:** benefit repeats in the chosen target class without
unacceptable read latency, lower traffic, memory pressure, GC wear/space or
error/lifecycle regressions; document the keep/reject verdict in this roadmap
and qualify only through the authorized supported test scope.

### Phase D — investigate direct compressed zswap handoff (separate design)

The ideal later pipeline could hand off the **already compressed** zswap
payload, avoiding both zswap decompression and swapz recompression. This is
*not* the same feature as Phase B RAW bypass. Before any implementation,
specify compressor/encoding compatibility (zswap need not use SWZ LZ4),
bounded payload size, integrity/CRC, ownership and release handshake,
crash/recovery/format semantics, read-side decoding and GC relocation.
Do not reinterpret opaque zswap payload bytes as ordinary SWZ records.
A new SWZ representation/format requires its own independent justification,
compatibility rules and measured admission gate. If interoperability is not
worth the complexity, retain the Phase B/C outcome.


### Phase E — folio locality (ID113: measured cohort correlation)

**Hypothesis.** When real swap WRITEs originate from the same large RAM
folio, those pages are more likely to cause **nearby lower-device READs**
than equally adjacent logical swap pages or pages merely admitted together.
This is unproven; the initial task is source-aware telemetry, not packing.
The full technical reasoning, kernel-version distinctions and identity
model are in [context.md](context.md).

**E1 — pin the source and identify the WRITE observation boundary.**
Reinspect the installed kernel and the relevant upstream release before
assuming the shape of a swap BIO. The audited Ubuntu 7.0.14-based source
used one block-backed BIO per folio; newer upstream
`swap_io_ctx` can merge compatible folios. Swapz's current 4KiB split
retains bvec page references and can already observe compound folio
membership. Do not make larger upper BIOs a prerequisite. Keep the
original upstream BIO-group token, if later desired, as a distinct
kernel-interface proposal.

**E2 — collect bounded WRITE-cohort observations.** While a write
window owns its accepted BIOs, inspect page/folio identity, folio order
and position of each 4KiB slice in that folio. Group pages from a
single safely observed source folio into a **window-local cohort**;
also retain comparison controls for logical adjacency and arrival order.
No persistent folio pointer, added reference extending the RAM's life
through swap-in, unbounded allocation or new SWZ metadata is allowed.
Ordinary ownership, fences and publication stay unchanged. Report window boundary censoring explicitly: a large folio can span several 64-record windows, and absence from a given window does not imply a different folio. Copy scalar hints before source BIO ownership ends.

**E3 — correlate through authority, not READ folio identity.**
Maintain a fixed-size, volatile cache of
`(logical_page, successfully_committed_generation) -> cohort_id`. The reviewed **initial prototype budget** is 256 preallocated 64-byte entries (16KiB), with a numeric cohort/epoch, observed order/index and committed extent identity; this is a proposal, not active configuration.
Publish associations **only after** the lower write succeeds and mapping
authority commits; handle overwrite, generation changes, DISCARD, slot
reuse, failed/partial writes, GC relocation and cache eviction without
stale attribution. Invalidate tags on zero elision; clear cache safely on cohort/epoch wrap and target teardown. Keep cache updates confined to the serialized authority worker. Cache absence is unknown; generation mismatch must
never match. A later target READ uses its **current authoritative
logical page/generation** to look up the WRITE cohort; its destination
folio may be a new allocation and is not compared to the earlier WRITE
folio. Cohort records are telemetry only, never a correctness dependency.

**E4 — test whether the signal predicts real lower READ co-access.**
Measure timing and sequences of later **backing** READs attributed to
each known cohort, with controls for logical adjacency, arrival order,
compression length and read readahead. Record upper WRITE `REQ_SWAP` provenance without requiring `REQ_SWAP` on upper READs or confusing lower swapz BIO flags with upper origins. Separate observable demand
READs from speculative readahead where possible; target-only reads
cannot see swap-cache or zswap hits and must not be described as all
application accesses. Report cohort coverage/evictions, false/stale
lookup prevention, hit-rate denominators, time windows, conditional
co-access lift over controls and independent lower READ bytes/requests.
Existing `series_thp()` tests validate THP-backed I/O handling only:
they are **not** evidence of swap-in correlation.

**E5 — consider one geometry-preserving layout candidate only if
E4 is positive.** The current greedy largest-plus-partner ordering
precedes a DP planner that optimizes the supplied record length sequence.
Do **not** generally sort the whole window by folio before DP. The first
candidate may permute **only compressed records with exactly equal encoded
lengths after greedy ordering**, under the already-accepted independent
window and the existing fences. Verify whole-window equality of physical
bytes, bounded cold-read cost, extent count, exact extent classes, lower
run splits/requests, segment alignment padding and segment-tail waste.
Account for any extra CPU/planner cost. An implementation that adds no explicit wait may still increase dispatch latency by doing extra permutation work; measure it. Reorder neither RAW nor
different-length records in this first candidate. Never wait for a
future cohort member or postpone an otherwise dispatchable lower WRITE.

**ID113 exit gate:** a bounded, generationally safe correlation cache
with no held original folios; native/safe loaded correctness of stale
entry and publication cases; and evidence that same-folio membership
predicts later backing READ co-access **beyond adjacency and arrival
order**. Only then may the separately gated equal-length placement
policy be evaluated. Promotion requires preserved byte-exact readback,
zero new order/authority violations, no lower dispatch delay, and no
increase in physical runs, bytes, padding or cold-read amplification.
Otherwise retain observational telemetry or close the idea as refuted.

### Qualification and integration constraints

Native contracts and safe owned-RAM `null_blk` fixtures can exercise the
origin/RAW state machine without activating swap. Real zswap writeback,
swap-in, memory-cgroup interactions and accurate origin ratios require
separately authorized actual-swap qualification. Keep the single official
`make test` interface and the limited `make fast_test` development loop;
do not silently expand their privilege or device scope. The governing
regressions and loaded-safety gates are in
[testing_standards.md](testing_standards.md).

This blueprint stays **future work** until a measured, qualified source
revision proves otherwise. It does not override the immediate scheduler
queue or change the work-conserving four-record dispatch priority.


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

1. Run ID114's default `make fast_test` baseline: three repeated SATA mixed,
   NVMe4 mixed, fast mixed, fast QD4 and fast QD8 pairs. Discard NOISY/UNKNOWN
   performance comparisons; retain absolute raw/swapz throughput, p99 and lower
   WRITE bytes/requests rather than deciding from a percentage delta alone.
2. Use the compact K=1 profile plus `build/tests/fast-test/latest.json` to
   distinguish ordered-worker partial phase wall, scheduler diagnostics,
   accepted-idle scheduling delay,
   preparation/copy, ordering/planning, pack/CRC, lower service,
   completion/publication and the synchronous four-record reissue cycle.
3. Choose **one** narrow production-C change only if that breakdown identifies
   a repayable software cost. Preserve the four-record service threshold,
   single-slot ownership, one unbound preparation producer, the 64-slot
   reservoir, ordinary LZ4 acceleration one, packed placement, circular
   allocation, ID63 and SWZ geometry.
4. Keep or remove the candidate with matched screened `make fast_test` evidence,
   refresh the ARM64 history plots, and require an exact-source owner
   `make test` before promotion. Zswap Phase A and ID113 folio locality remain
   later architecture/evidence tasks.


The nine-idea review now has direct evidence for first-window lead (ID140)
and mixed barrier sensitivity (ID141); sleep/spin remains the unpromising
ID137 pilot. ID142 identifies ACK-loop interference, and the bounded ID143 handoff is now
qualified with a measured throughput/I/O trade-off. The remaining continuous
NVMe deficit needs fresh attribution; it is not explained by wave barriers. ID144 observes
completion-CPU locality without establishing causality; ID145 counter padding did
not justify retention. A future completion-delivery experiment must first audit
callback lifetime, CPU-hotplug fallback and drain ownership; these observations
do not authorize a cached-READ admission shortcut. Selected-wait idle,
accepted post-lower delay and deferred-ACK wall have different scopes and may
overlap other work; never sum them into a CPU total or call the first the whole
device-idle budget. Submitter compression and lockless admission remain
conditional candidates, not consequences of summing concurrent lock waits.

A dm-linear arm would be a DM calibration reference, not an exact unavoidable
overhead budget: DM has target-specific fast paths, while swapz owns clones,
ordering and completion state. Direct BIO submission and polling are separate
experiments. Upstream Linux v7.0 null_blk polling bypasses its timer completion
path, so enabling it only for swapz would change the device model relative to
raw ([driver source](https://raw.githubusercontent.com/torvalds/linux/v7.0/drivers/block/null_blk/main.c)).
A cached READ in admission requires pinned immutable cache/authority views plus
pending same-page WRITE, GC, DISCARD and fence safety; a generation check alone
is insufficient. Early ACK from staging remains a separate architecture
proposal requiring an explicit change to the lower-success publication and
failure contract; it is not authorized as a scheduling optimization.

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
  retains its separate acceleration control, default 4 since ID115.
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
