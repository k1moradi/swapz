# Roadmap

**Immutable naming policy (read before every prompt):** The project is `swapz`; the kernel module is `dm-swapz.ko` (loaded as `dm_swapz`); the Device Mapper target is exactly `swapz`; and the module alias is `dm-swapz`. Never put implementation-generation numbers in product, module, target, source-path, report, workflow, helper, or schema names. `SWZ` is the current unversioned on-disk format identity; do not assign a format version until an incompatible format boundary is justified.

**Single official test command (read before every prompt):** Run `make test` at the repository root for every supported swapz test and benchmark. A complete run must report BLOCKED (nonzero) if safe noninteractive privileged qualification cannot run. Do not create, publish, recommend, or document alternative test commands; the sole owner-approved exception is the development decision loop `make fast_test`, which never qualifies a source, never writes or publishes `test_results.json` and never replaces `make test`. Private scripts and CI jobs are implementation details, not operator interfaces.

This file is the project's **rolling engineering blueprint**: active priorities, proposals, decisions and acceptance gates. Linux MM/swap/zswap semantics and implementation context live in [context.md](context.md). Completed experimental transcripts belong in Git history.

## Current owner requirement: fixed production compression stack

Every emulated device must run the production delta64 + `DELTA64_SHUF8`
8-byte byte-plane shuffle (owner-confirmed byte shuffle, not bit-level) + LZ4 stack with delta64
rescue enabled. This is a main product requirement, not an experiment selector.
Do not spend qualification time on delta64-off benchmark arms, off/on A/Bs, or
delta64-off plot/history series. Historical rescue-off results remain evidence
of past decisions only. Low-level decode/debug compatibility coverage may still
exercise legacy/disabled states, but no disabled state can qualify or represent
an emulated-device performance result.

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

The last fully qualified ARM64 production C,
`d2b66acb8c7eed99bbcfb6c89000df2da743ec83`, passed all five
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
remain LZ4-only. The newer x86 qualification is separate, as below.

On the receiving native i7-1185G7/eight-CPU host, unchanged ID148 production C
at source `a2b556998a8554b4f64960c77d6818fce1d4e811` passed all five stages,
including ID36; report `c0feb2127c05ffde1826e250e1ade55918d21448` was pushed.
Firmware verifies 16 GB LPDDR4 at configured 4267 MT/s, and boot/runtime evidence
confirms AVX-512 xstate and selected transform/inverse. This is not measured
RAM bandwidth or physical NVMe fidelity. The direct-BIO pilot below was removed,
and production C remains byte-identical to that baseline. Exact-host history
uses the owner-confirmed legacy-report registry rules in the testing standards;
unconfirmed legacy candidates never enter the pooled series automatically.

Main now also contains the ID148 lower-callback lifetime repair in
`2aa3ba06520fbf3a723294d7d7dd09cdd45e6502`. Its owner run was deliberately
interrupted after the owner reported a very busy host; report `ff66c705b152`
is **BLOCKED**, exit 2, with stages 1–4 and loaded smoke/ACK/RAW-read gates
passing but the full matrix and ID36 unfinished. The harness reports the
terminated raw replay as a bounded timeout; the local stop record identifies
the intentional TERM sent to its positively owned replay timeout. This is not
a demonstrated source regression or a completed qualification. Treat the run's
partial performance as unusable; it adds no historical point. Owned mapping
cleanup completed. Hold further benchmarks until the owner says the host is
free, then run exact-source owner qualification before promotion.

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

1. **SATA/NVMe mixed envelopes (owner reports for `9123b811` x86 and
   `7ff94fd4` ARM64: SATA -22.5/-33.8%, NVMe4 -54.0/-39.7%, NVMe5
   -47.8/-40.1%).** Lower savings stay intact (bytes saved 28-30%, requests
   saved 84-91%), so the loss is lower-WRITE service time on one lane, not I/O
   volume. **Leading hypothesis, not a proven diagnosis: single-lane pipeline
   recovery.** The interval from one lower WRITE completing to the next one
   starting is roughly a fixed per-run cost (~31-35 us on x86, ~40-59 us on
   ARM64) while device service per run ranges 21-122 us, so the faster the
   device the larger the idle share. Existing counters, measured window:

   | Host / envelope | swapz vs raw | Lane busy | Runs | Pages/run | Service/run | Gap/run | Completion→publication/run | Accepted-work idle | Deferred ACKs | READ p99 raw/swapz |
   | :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | :--- |
   | x86 SATA | -22.5% | 76% | 1053 | 11.7 | 108 us | 34 us | 4.5 us | 0.3 ms | 5348 | 114/240 us |
   | x86 NVMe4 | -54.0% | 51% | 1157 | 10.6 | 33 us | 31 us | 3.9 us | 2.3 ms | 6547 | 38/97 us |
   | x86 NVMe5 | -47.8% | 38% | 1335 | 9.2 | 21 us | 35 us | 3.9 us | 5.1 ms | 8611 | 36/102 us |
   | ARM64 SATA | -33.8% | 68% | 1057 | 11.6 | 122 us | 59 us | 5.9 us | 7.4 ms | 4443 | 260/187 us |
   | ARM64 NVMe4 | -39.7% | 48% | 1510 | 8.1 | 39 us | 42 us | 4.4 us | 12.8 ms | 8736 | 110/136 us |
   | ARM64 NVMe5 | -40.1% | 38% | 1905 | 6.5 | 25 us | 40 us | 4.6 us | 18.2 ms | 8951 | 88/145 us |

   Busy is `lower_write_wall_ns` over measured wall; gap/run is the remaining
   wall per lower-WRITE request; completion→publication is
   `pipeline_post_lower_wall_ns` per request. `1 / busy` (1.3-2.65x) is a
   **ceiling** at 100% utilization and unchanged run size, not an expected gain;
   closing any gap can expose another bottleneck. Interpretation limits:
   `k1_ready_wait_windows=0` means only that no completed window had to wait
   for a pending lower WRITE (the policy never sealed while the lane was busy),
   not that no accepted work existed during lower I/O. `accepted_work_lower_idle_*`
   starts only when the owner retains a staged window with the lane idle; its
   small totals (0.3-18 ms against 36-77 ms of lane idle) say that retained
   staged work explains little of the idle: 65-86% of each gap has no
   attributing counter (owner pickup, upper round trip of ACK, writer reissue
   and admission, READ service on the owner, and sealing, which has no per-gap
   counter). Owner CPU/wall
   (19-25%) does not show where the owner is off-CPU, and admission→owner
   (15-21 us per WRITE) may overlap lower service. ID178 partitions exactly
   the completion→next-submit interval before any architecture change.
   Envelope arms still lack `host_cpu`, so host-bound NVMe rows cannot yet be
   separated from host contention. History: pre-ID108 SATA wave traces showed
   stragglers staged behind the first K=1 WRITE leaving ~17 us after its
   completion; ID109 straggler waiting traded the same time it saved and the
   post-ID107/ID108 K=2 trial (ID110) reached depth two without useful-service
   gain and with more requests.
2. **Fast QD4 (latency guard; x86 +4.4% MET, ARM64 -14.7% MISSED).** K=1
   completes all four writers together, so their reissue spread sits on every
   cycle while raw overlaps it. ID110 did not improve it because four-record
   windows without followers still dispatch synchronously. Reopening needs a
   separately justified shallow-window ownership policy; deprioritized behind
   item 1.
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
| 36 | Heavy-CPU plus low-RAM qualification | **1 qualified; parent orchestration margin repaired again / owner requalification pending** | This four-thread x86 host later passed ID36 at source `ac6c71e` (report `e9709aa`) with the same production kernel C as current tested source `49618ee`. Current report `c2306f7`, collected under intentional background browser/video load, reached swapz packed-read with `memory.high` +107,100, CPU PSI +490,890,748 usec, no reported OOM/OOM-kill, then the 680s pair watchdog expired before the active 280s candidate reported its own timeout. That is parent orchestration-budget exhaustion, not evidence that the candidate exceeded its forward-progress bound. Keep the 576MiB pressure set, `memory.max=896MiB`, 2x niceness-10 CPU burners, allocation-bounded 32 persistent packed-read lanes and the unchanged 280s per-candidate bound; give the pair 840s (`2*280+280`) and the top-level helper 960s so pressure-throttled barrier/setup/comparison/teardown cannot preempt a legal child. Owner pass still requires positive high/CPU-PSI deltas, zero OOM/OOM-kill, byte-exact readback and teardown. |
| 37 | K=1 ping-pong WRITE pipeline | **1 qualified / keep; release gate open** | Latest five-pair fast sustained-write evidence shows async/sync QD4 +1.66% CI [+0.33%,+3.00%], QD8 +23.88% [+18.52%,+29.24%], and QD32 +22.15% [+15.65%,+28.65%]. QD8 lower requests fall 17.96%; QD32 requests fall 9.96% while bytes are statistically neutral. Keep the fixed one-slot path and existing activation gates; low-RAM/heavy-CPU remains a release gate. |
| 38 | Shared accumulator with K>1 lower-write slots | **5 refuted / removed** | Repeated depth-1/depth-2 evidence did not establish a useful service benefit. Production is fixed at one slot, and the second-slot allocation/append path plus runtime selector are removed. Reopening K>1 requires a new workload and an explicit architecture experiment. |
| 39 | Latency-first bounded parallel READ service | **1 promoted / selector and routine A/B retired** | The retired `swapz-read` helper workqueue remains absent. The final five-pair ARM64 fast-model decision at source `11fbc839...`, with ID63 off, showed fan-out +17.9% mixed WRITE/READ throughput (95% CI +17.2..+18.5), -48.7% mixed READ p99, +67.9% sequential READ throughput and +101.8% seeded-random READ throughput while raw-control drift overlapped zero. Keep ordered-worker private-slot fan-out fixed on; remove the `parallel_reads` module selector and routine ten-session A/B. |
| 40 | Freeze first, then start LZ4/CRC | **5** | Rejected; compression belongs during collection. |
| 41 | Per-lane isolated write accumulators / 2xN packing queues | **5** | Reject by default; destroys global packing view and risks request inflation. |
| 42 | Explicit serial-vs-parallel lower queue model + lower in-flight-depth telemetry | **1 completed measurement** | Owner-qualified. Slow hwq=1 stays at sampled peak depth 1; fast raw reaches >1 while swapz remains at 1. Keep the geometry and telemetry as mandatory evidence for concurrency claims. |
| 43 | Huge/compound-page RAM input support (folio/THP/hugetlb), not only 4KiB page inputs | **1 qualified / covered** | Explicit multi-bvec, non-zero bv_offset, and THP compound folio backing qualified on owned RAM with kernel observation counters (`bio_segments_gt1`, `bio_segments_max`, `bio_nonzero_offset`, `bio_compound_folio_pages >= 128`, `bio_copy_fallback_pages`). The direct-I/O fixture now requires an aligned 2MiB anonymous range to collapse with `MADV_COLLAPSE` before counting THP coverage; `MADV_HUGEPAGE` alone was only a hint and could leave the test on base pages. Byte-exact across segmented, THP, and cross-mode reads/writes with zero failures. Larger base PAGE_SIZE/native larger records remain architecture work. |
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
| 105 | `make fast_test` development loop | **1 owner-requested / keep** | Runs native/replay contract checks and three paired repeats per selected owned-null_blk scenario (six mixed/QD scenarios by default), with compact raw/swapz, critical-path and synchronous-cycle tables plus telemetry in `build/tests/fast-test/latest.json`. `CONTENT=representative` is opt-in and requires the owner-supplied page file in ID177. Never qualifies or publishes; `make test` remains the only qualification command. |
| 106 | Pressure-hand inline extension when LZ4 is cheap | **5 no effect / removed** | Hand closes on the NVMe trace happen when the accepted FIFO is genuinely dry, not over an unprepared queued head, so the gate never fired. |
| 107 | Unrelated READs stay independent after a K=1 window is dispatched | **1 owner-qualified (`03becc0`, report `b5227ca`)** | With an empty collector and an active run, a READ took the dependency path and its empty flush slept the ordered worker for the whole lower WRITE (traced ~127 us/wave in D state) while cache hits and stragglers queued. Committed mappings stay authoritative, so the in-flight run fence alone applies; window evidence and the deadline-after-READ flush still need an open window. SATA mixed swapz 188 -> 206 MB/s, READ p99 0.40 -> 0.24 ms. |
| 108 | Acknowledge a finalized run after the next window reaches the lane | **1 owner-qualified (`03becc0`, report `b5227ca`)** | Finalize delivered ~20 `bio_endio()` wakeups (1–5 us each, preempted by co-located writers) before dispatching the staged straggler window. Deferral (only with staged/queued work, preemption-disabled batch, delivered before any lower wait and before the work item returns) cut first-done -> second-issue from ~100 to ~17 us: SATA mixed 206 -> 216–223 MB/s; QD1/QD4 unchanged in interleaved A/B. A dedicated completion thread was not needed. |
| 109 | First window of a mixed wave waits for the learned width | **5 no throughput gain / removed** | Gating the first mixed window (chain_completed == 0) like ID102 cut SATA/NVMe lower requests 1047/1255 -> 868/1056 but left useful WRITE flat and raised idle-bound closes; under trace perturbation write p99 jumped to 2.3 ms. Stragglers arrive ~35–80 us late, close to what one fixed device latency saves. Reopen only with K=2 data showing merge beats overlap. |
| 110 | Fresh two-run lower-WRITE overlap after ID101/ID107/ID108 | **5 no demonstrated service benefit / removed** | ARM64 development experiment on `03becc0`/report head `b5227ca`, 2026-10-29: two disjoint immutable slots, FIFO publication, same-page append fences, bounded paused-group capacity and four-record successor service. Observed depth reached 2 on SATA/NVMe/fast mixed. Adjacent K=1/K=2 blocks, three `make fast_test` repeats each (mean useful WRITE MB/s): SATA 182.19/177.11, NVMe4 237.33/234.14, fast QD4 61.91/60.81, QD8 95.80/92.08, fast mixed 47.54/48.39. Lower-WRITE requests changed +21.2/+3.6/+0.3/+9.9/+3.9%; SATA lower-byte ratio 0.696/0.702 and fast mixed 0.762/0.765. Raw SATA 329.14/322.33 and NVMe4 422.61/439.16 show residual host drift; these pre-ID111 observations have no quiet-window screen and are directional, unpaired development evidence, not confidence-qualified regression claims. No demonstrated service gain repays the added requests, ownership state and buffers; restore K=1. Rootless, W=1/W=2, loaded smoke, full default development scenarios and ID36 passed. Reopen only with a materially different workload/policy and repeatable useful-service benefit without fragmentation; depth-two activity alone is insufficient. Authority blocker: swapz_authority keeps one paused batch group (batch_pending, batch_segment, batch_first_sequence and batch_hashes are singletons for one physical segment), so a second in-flight run needs a second paused group or segment with its own rollback and replay rules. |
| 111 | Compact automatic host-noise screen for development comparisons | **1 owner-requested / keep** | `make fast_test` adds 200ms pre/post quiet CPU/PSI/steal deltas, timed steal and >10% same-scenario raw-repeat spread checks. `NOISY`/`UNKNOWN` results set `performance_validity.performance_usable=false`, retain all evidence and print compact reasons. Timed workload CPU/PSI alone is never external-noise proof. Thresholds are conservative screening heuristics; `SCREENED` is not idle-host proof, single repeats cannot bound control drift, and owner `make test` qualification/ID36 is unchanged. |
| 112 | Per-round ARM64/NEON VM performance history plots | **1 owner-requested / keep** | After every optimization round, regenerate default-LZ4 mixed useful READ/WRITE, mixed p99, lower-WRITE savings and persistent-WRITE QD plots plus source-mapped CSV/JSON under `build/history/arm64-neon/`. Initial history through report `b5227ca` selects 51 owner-PASS NEON/seven-CPU reports from 230 revisions. Exclude failed/blocked/other-host and unqualified trial data; use each report's own raw controls and break kernel/model/content/replay discontinuities. Descriptive history never establishes causal gains or physical wear. |
| 113 | WRITE-folio locality as an equal-cost packing hint | **6 source audit / representative evidence gate** | See [reviewed measurement proposal](context.md). Current 4KiB splitting preserves page references but no explicit parent-BIO token. READ destination folios cannot identify earlier WRITE RAM; correlation needs bounded logical/generation tags and live-owner-only cohort discovery, with censoring and reuse handled explicitly. ID43 THP direct I/O is functional coverage, not real swap-locality evidence. Linux 7.0 block swap and newer `master` batching differ. Keep layout unchanged until folio membership predicts backing READ co-access beyond logical adjacency. A later policy must preserve full byte/read/extent costs and physical run/tail geometry; equal-length permutations are a narrower candidate than arbitrary reordering. No actual-swap collection or larger upper BIO is authorized by this design. |
| 114 | Focused K=1 critical-path profiling before another scheduler change | **2 passive instrumentation / ARM64 baseline collected** | Keep K=1, the four-record service rule, one preparation producer, the 64-slot reservoir, LZ4 acceleration one and SWZ unchanged. `make fast_test` defaults to three repeated SATA mixed, NVMe4 mixed, NVMe5 mixed, fast mixed, fast QD4 and fast QD8 pairs with existing host-noise screening. New interval telemetry measures accepted WRITE -> first ordered-worker ownership plus successful synchronous four-record wall/lower/non-I/O and completion -> next-four-record reissue gaps; existing counters supply ordered-worker CPU, accepted-idle unscheduled time, preparation/copy, ordering/planning, pack/CRC, lower service and publication. Detailed runs stay in `build/tests/fast-test/latest.json`; compact output is diagnostic. Choose at most one narrow production-C candidate from screened evidence, keep/remove it with matched `make fast_test`, refresh ARM64 history, then require exact-source `make test` for any retained change. |
| 115 | Delta64 rescue on by default | **1 owner decision / owner-qualified (`b86fefd`, report `0d97e99`)** | Owner decision after ID67: the transform is cheap and positive-content evidence is strong. Report `b5227ca` paired A/B on the delta64-positive fixture: compression ratio ~1.46 -> ~1.94, lower WRITE bytes -25%, useful WRITE +26% (+16..+35%), p99 -22%; transform 0.13–0.16 us/page on ARM64/NEON and LZ4 on transformed pages 4.6–5.0 vs 5.4–5.8 us/page untransformed. `delta64_rescue` defaults to 1 (0 disables) and `delta64_lz4_acceleration` defaults to 4, the second-pass value the A/B qualified (it was 1, an unqualified configuration, when rescue first became default-on). Standard mixed and write-only sessions historically included rescue-off controls, but that comparison is now retired: every emulated-device session runs delta64 + DELTA64_SHUF8 + LZ4 fixed on, and current history plots exclude rescue-off reports. Owner `make test` on `b86fefd` (report `0d97e99`; the earlier `de79f2e` run failed only on the ID114 profiling-epoch acknowledgement that `b86fefd` fixed) passed all five stages with standard sessions at rescue 1 / second-pass acceleration 4. Ordinary medium mixed content: the classifier scored every page, made 0 attempts and adopted 0, so lower bytes stay -25.8% (fast) / -30.5% (SD); its loaded wall is 81–155 ns/page in async mixed sessions (it takes the page's first cache misses). Fast mixed +10.8%, SD mixed +404%, fast QD1/4/8/32 -4.9/-11.3/+28.4/+50.0%, SD QD +0/+266/+252/+268%: unchanged within run-to-run noise versus rescue-off `b5227ca`. Paired positive A/B (off arm now pinned `--no-delta64-rescue`): useful WRITE +29.5% (+24.6..+34.3), lower bytes -25.0%, p99 -21.0%. Single directional delta-positive envelopes moved SATA 0.51->0.38 and NVMe Gen4 0.25->0.30; this remains historical evidence. Current policy does not reopen rescue-off benchmarking; investigate future regressions against raw and the fixed production stack instead. |
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
| 146 | Attribute endio wakeup path without a new completion mechanism | **1 passive attribution / no source change** | Two fixed medium native NVMe5 sessions (persistent and matched waves) on qualified C, observed only between native GO and fsync return. Map-aggregated bio_endio/try_to_wake_up/ttwu_queue_wakelist kprobes preserve paired entries/returns, no overflow or leftover state, and all 16,384 data completions per swapz phase. One additional WRITE-op completion per phase resolves through DWARF/disassembly to the zero-sector PREFLUSH success branch at swapz_process; account for it separately. First-seen raw/symbolic stacks separate direct target calls from nested DM and interrupted lower-I/O ancestors; never sum those populations. Both final-image oracles pass. Most observed wake-list calls during direct READ endio are accepted (95.15% persistent, 77.12% waves), consistent with remote task activation; IRQ wakeups can also occur inside those intervals. Nested kprobes contribute overhead within the observed READ endio/wakeup means (~10/~5 us), so these are instrumented path observations, not exact CPU, a removable budget, production timing or a source speedup. No raw cost/locality comparison. Native hardware cycles are unavailable on this VM. Production C unchanged; local BPF source, raw aggregates, population checks, call-site proof and analysis: build/optimization-round/completion-wakeup. |
| 147 | Already-copied READs join the existing published-ACK handoff | **1 weakly exercised pilot / removed** | Three successful READ paths defer only notification while a lower WRITE is pending; copied BIO bytes and all authority/cache/scratch remain with their established owners. Reuse ID143 list, 4..64 gate, helper, inline fallback and drain; no new queue, worker, I/O buffer or CPU-targeted callback. Fixed control/candidate/control, three repeats on six medium workloads (54 byte-exact owned raw/swapz pairs). Post-drain candidate counters show 15,653 deferred READs but only seven actual helper READ completions across 18 target sessions: entering the list does not establish useful offload. Five scenarios lack a complete usable three-block comparison under the declared noise screen; persistent after-control raw spread reaches 139.3%. Only fast WRITE QD4 remains fully screened, with descriptive normalized changes -5.14% vs before and +0.89% vs after; it has no READ activity and establishes no READ-policy benefit. No significance/equivalence or causal regression claim; no replacements. Audit also finds a deferred READ can remain queued through a subsequent synchronous READ wait, contradicting the candidate's broad before-any-lower-wait comment. Any renewed READ deferral needs explicit notification boundaries and meaningful helper activity before performance confirmation. Candidate module builds and byte oracles pass, but its source-contract run retains a changed-call-site assertion error; it is not qualified. Remove C, counters and test edits; restored qualified d2b66ac C passes all 89 source contracts. Local exact sources, hashes, plan, activity, exclusions and analysis: build/optimization-round/read-completion-handoff. |
| 148 | Lower-WRITE completion publication and owner notification share the drain gate | **1 controlled race verified / busy-host owner run interrupted** | Adapter audit finds the callback published lower_done after releasing queue_lock, then still dereferenced ctx to queue the owner. A waiter can observe completion, finalize the last upper BIO and reach the final drain gate before that notification; no kernel UAF is claimed observed. Move complete plus mod_delayed_work inside the existing queue-lock critical section and make unlock the callback's last target/slot access. This preserves the established admission/workqueue lock order, completion/error semantics, K=1 ownership and publication policy; no new resource or speedup claim. Actual callback-body native test fails on old source when a controlled waiter passes the final gate at complete, and passes on repaired source under both dm-io ABIs, success, ordinary error and separate unsupported bitmap. Full rootless suite and W=1/W=2 builds pass with known warnings. A fixed default development run passes all 15 byte oracles; SATA/NVMe4/fast mixed are NOISY (raw spreads 19.7/32.7/39.5%), so exclude performance inference. Fast WRITE QD4/QD8 are SCREENED but this is not a source A/B. Owner run on 2aa3ba0 was intentionally stopped for the reported busy host: report ff66c70 is BLOCKED, exit 2, after stages 1–4 and loaded smoke/ACK/RAW-read gates passed; remaining matrix/ID36 unfinished. Owned cleanup completed. No performance evidence or history point is accepted from the interrupted run; wait for owner host-free notice before benchmarking again. Exact-source qualification remains required. READ callback already ends with complete and performs no following slot access. Keep direct-BIO work separate. Local exact sources, red-control proof, plan and logs: build/optimization-round/lower-completion-lifetime. |
| 149 | Direct BIO for the detached immutable lower WRITE | **1 unpromising x86 pilot / removed** | After unchanged-source x86 qualification (`a2b5569`, report `c0feb2127c05`), the exact portable draft compiled and passed 91 source contracts plus 108 owned raw/swapz pairs (216 byte-exact arms). One reusable parent BIO and 64 vectors replaced only detached dm_io submission; existing service timer, callback drain gate and lower-success publication stayed intact. Compiled context 24,832 -> 25,984 bytes. Prospective three counterbalanced source rounds, two repeats per block, nine content/workload cases, +3% practical floor, three primary normalized-WRITE endpoints, 98.333% paired log-effect intervals and exact direction cutoff 0.05/3; both repeats SCREENED/provenance-matched and <=10% paired raw drift required, no replacements. Primary SATA n2 -0.38% [-11.95,+12.70], p0.5; persistent NVMe5 n1 +3.30%, no interval, p1; fast mixed n3 -0.41% [-2.02,+1.23], p0.25. These do not establish gain/loss/equivalence or justify larger confirmation. Five scenario-round exclusions were recorded. Mixed arms exercised hundreds of detached runs, while QD1/4 had zero; QD4's noisy-direction +6.11% point is not adapter benefit. No lower-I/O/p99 benefit repays a new backend: fast mixed requests +0.69% descriptively; entropy NVMe4 +1.99% with equal bytes; QD8 WRITE p99 4.73 -> 6.02 ms descriptively. These are not qualified regressions. Restore exact qualified C and source tests; remove the temporary fast_test native hook. Forced-split/genuine child-error, ARM and exact-source candidate qualification gates were not completed. Do not repeat the same draft without new material mechanism/workload evidence. |
| 150 | Bounded submitter-context preparation before ordered ownership | **4 x86 correctness qualified / host-specific service trade-offs** | Move ordinary WRITE LZ4/payload-CRC preparation into the already-admitting task without moving FIFO admission, lower I/O or authority publication. Up to eight preallocated submitter scratch lanes share the existing 64 prepared-page reservoir; each claim is allocation-free and failure falls back immediately to the qualified single producer/ordered path. The descriptor is admitted first, marked submitter-owned under queue_lock, and the ordered worker defers that FIFO head until a release/acquire handoff publishes a terminal prepared representation. PREFLUSH/FUA and non-task contexts retain the old path. Existing LZ4/SWZ bytes, K=1, four-record floor, planner, allocator and publication contract are unchanged. New status separates submitter claims/misses/active peak/owner deferrals and submitter wall/CPU/LZ4/copy/CRC time. First x86 owner run on `0f42e018` passed stages 1–4 and all 384 segmented/THP byte-exact writes/reads, then BLOCKED because `bio_copy_fallback_pages` omitted the new submitter owner's fallback counter (`segs_gt1=384`, `segs_max=4`, `nonzero_off=384`, `compound=256`, reported fallback=0). Fix only the status aggregation to include ordered + background producer + submitter fallback counts; data-path bytes and ownership are unchanged. Second x86 owner run on `14cbd609` passed compound/THP, live-GC/pressure, DISCARD/TRIM, suspend/drain, retained WRITE/FLUSH faults and packed placement, then BLOCKED in the completion-handoff fault fixture. The production failure path and controlled native handoff/failure interleavings remain intact; the loaded fixture still injected on lower-WRITE attempt 32, which ID150's changed preparation timing can reach before a real offloaded batch. Move only that test injection to guaranteed-late attempt 256 within the fixed 16,512-WRITE workload and emit all fault predicates on failure. Third x86 owner run on `91e3013e` passed the complete owned-null_blk smoke, including real completion handoffs and injected terminal failure, then BLOCKED in the RAW-read fan-out pair because its `prep_lower_write_overlap_starts>0` gate observes only the old background producer, not submitter preparation. Revise only the loaded pair activity gate to require actual producer lower-WRITE overlap or completed submitter preparation with enabled policy, claim conservation and drained ownership; report each separately without claiming submitter/lower-I/O temporal overlap. Fourth x86 owner run on `1599ad45` passed all loaded correctness phases, RAW-read fan-out, complete serial/fast mixed and QD1/4/8/32 saturation pairs, SD/SATA/NVMe envelope, coalescing, and ID36. Reporter alone marked FAIL: every enabled delta64 positive-control arm classified, attempted and adopted 4096 pages but `delta64_prepare_pages=0` because the same 4096 pages were submitter-prepared; repair the reporter to count background or submitter preparation while retaining actual delta64 and conservation gates. Evidence also shows fast mixed async/sync useful WRITE 118.69/119.88 MB/s, paired -1.0% CI [-1.7%,-0.3%], lower WRITE requests 1285.4 vs 1060.8; this is not an ID150 service win and requires a keep/revert decision only after qualified evidence review. A fifth owner attempt on an SSE2-only legacy x86 host at `0c9c8fb` passed build/native/W=1/W=2 plus oracle, compound BIO, live-GC/pressure and DISCARD/TRIM, then BLOCKED before suspend because the userspace observer never sampled the existing 4ms retained window. This is an observer-schedulability limit, not an SSE2 codec failure: production C is unchanged from the modern-host run that passed suspend/drain. Keep the physical/production retain ceiling at 4ms, but permit an explicit 64ms retain only on null_blk and use it for the lifecycle oracle so a slow status round-trip can observe an open window; keep performance arms at their qualified retention settings. Require an exact-source owner `make test` rerun; then compare persistent NVMe5 plus SATA/fast mixed and QD4/QD8 to the qualified x86 baseline. Keep only if useful service improves without correctness, lower-I/O, p99 or ID36 resource-pressure regression. Pre-rerun review found a candidate-only wake defect: `swapz_map()` still woke the CPU-bound ordered owner (ID104) for a submitter-claimed WRITE before preparation began, so that pass could preempt the submitter, find the head still submitter-active, defer, and be woken again after release: up to two owner passes and context switches per WRITE, plus premature passes that can close smaller windows (a plausible contributor to the +21% fast-mixed request count above, not a proven cause). Admission now skips the owner wake only for a successful submitter claim; the submitter wakes after the release store with the unchanged retained/non-retained policy. Claims also require IRQs enabled at `->map` entry, and the drain-visible active count is decremented last. Compare `submitter_owner_deferrals` per claim before and after; it should fall sharply. Ownership, publication and representation bytes are unchanged. Sixth owner run on `bc8d15f` (pre-wake-fix) passed all five stages with only six live handoffs and one handoff before fault attempt 256 on the slow four-CPU host; the run on `58bd7af` then BLOCKED the same fault gate with zero handoffs before attempt 256 (loaded smoke phase 1 still observed live handoffs). One run each cannot separate the wake change from timing noise, and this gate already blocked once at attempt 32. Make only the fixture robust: inject at attempt 4096 and repeat the fixed series at most 16 times (>=4,128 guaranteed attempts), keeping the handoff-before-failure, exact-call, single-injection, upper-EIO and post-failure probe predicates. Modern x86 host then passed all five stages on `58bd7af` (report `8916874`; 552 live handoffs, 70 before the fault). Versus that host's `1599ad45` report, mixed deferrals per claim fell 0.31 -> 0.18-0.22 but fast QD4/QD8 rose 0.37/0.49 -> 0.53/0.64: most deferrals come from other writers' wakes, not this admission wake. Useful service is unchanged within these single-report means (fast mixed async 118.7 -> 117.6 MB/s vs sync 119.1; fast QD1 async 25.4 -> 23.3, n=1), so the wake change shows no benefit. The old four-CPU host on `203d100` passed the new handoff/fault gate, then FAILED the replay validator: `submitter_prepare_active_max` exceeded the four lanes because `58bd7af` decremented the active count after returning the lane, letting another submitter claim it first. Restore active-count release while the lane is held, keep the lane return as the final ctx access, and make drain wait for every lane/active tail before draining queues. The old host on `1ab1743` then BLOCKED earlier, in the live handoff probe: one fixed series under a 500-poll budget exposed no handoff. Same timing fragility as the fault gate; repeat that series (bounded to 16) and poll each pass until its writer exits. Rare handoffs on this host are themselves a service signal: the ID143 overlap seldom engages here. Old-PC owner rerun on `09e1cfaa40ca` passed build/rootless/W=1/W=2, oracle, compound BIO, GC/pressure, DISCARD/TRIM, suspend/drain, retained WRITE/FLUSH faults and packed placement, then BLOCKED only in the same completion-handoff fault fixture: the no-fault half had progressed, but the fault target reached call 4096 on pass 2 with `offloaded=0 active=0 failed=1 injected=1 upper_err=24`. This is another observer-geometry failure, not evidence of lost fail-closed propagation. Keep the product/no-fault 64-record window unchanged; for the correctness-only fault target use max_window=4 and test_fail_write_nth=65,535. Eight known zero elisions leave 16,504 nonzero WRITEs, so each fixed pass guarantees at least 4,126 lower attempts and 16 passes guarantee 66,016, while the handoff path remains eligible at its four-record minimum. The same-target requirements remain: real offloaded batch before terminal failure, exact single injection/call ordinal, drained completion ownership, upper EIO and post-failure EIO. |
| 151 | Correct preparation input-copy attribution | **qualified on modern x86** | Both preparation paths compress an immutable RAW snapshot after unmapping the BIO, so mapped-snapshot preparation is not direct mapped-BIO LZ4 input and must not count as direct LZ4 input. New mapped-snapshot telemetry and ordered-only direct-input counting preserve data, ownership and lower-I/O behavior. Loaded development validation observed 12,301 mapped snapshots, zero direct inputs and byte-exact output. Fresh IRQ-inclusive owner scheduling and exclusive sample attribution identify LZ4 state clear outside the ordered owner; scheduler/completion clocks overlap and must not be summed into serialized or removable CPU. The 14.1% raw drift forbids a performance decision. |
| 152 | Independent LZ4 state reuse with submitter preparation | **5 development pilot / removed** | The tested mechanism used the exported continuation API plus a zero-length dictionary reset after each call; it preserved independent blocks, changed LZ4 hash behavior as well as reset cost, and was not a custom small-table 4 KiB encoder. Actual-helper, kernel owner-class, RAW fallback, delta64 and >1 GiB successful-reuse checks passed. Fixed 12-round three-arm pilot passed 432 byte-oracle arms; persistent B/C -3.60% with 99.4444% interval -9.45..+2.63% missed the declared +3% floor. Stateless production and all temporary controls restored. Current submitter C/A +15.46% on persistent NVMe5, adjusted sign p 0.0352, carries scoped CPU/memory and fast-QD8 guard trade-offs. |
| 153 | CPU-targeted READ/WRITE completion | **5 fixed pilot / removed** | Actual-body native probes plus owned suspend/fault/drain and invalid-destination fallback gates passed; no live CPU-offline test was performed. The fixed 12-round counterbalanced pilot completed 24 source blocks and 288 byte-exact raw/target arm oracles, but persistent NVMe5 B/A +4.29% with a 98.3333% interval of -1.03..+9.89% and adjusted sign p 0.539 failed the declared benefit screen; SATA/fast remained inconclusive. Persistent lower WRITE requests +2.03% are descriptive secondary evidence, not an endurance improvement. No total kernel CPU reduction was established: native process system time excludes kernel workers and completion placement changes attribution. Production and temporary helpers were restored, with no replacement samples or owner qualification. Any future remote-completion design must re-prove target-owned callback-cell lifetime through the drain join and safe invalid/offline/same-CPU fallback; CPU placement is not free. |
| 154 | Direct admission contention diagnostic | **measurement incomplete; probe removed** | Six fixed source blocks/48 arm oracles pass. Try-lock observations find 11..13% contention in persistent NVMe5/SATA and 2..4% in fast workloads; failed-trylock fallback wall is not full lock wait/hold, CPU, or an upper bound on savings. All three NVMe5 perturbation pairs fail the raw-drift screen, and remaining intervals are wide. No production change selected; the perturbed evidence does not justify a lockless rewrite. Next bound hold/notification work and probe cost with stable controls. |
| 155 | Systematic admission hold/notification sampling | **diagnostic hypothesis; probe removed** | Twelve fixed blocks/96 arm oracles pass. One-in-64 samples place owner notification at roughly 0.34..0.94 us versus 0.02..0.06 us preceding non-submitter work; clock checks 13..21 ns. The sampled wall is only a partial IRQ-disabled hold interval: systematic one-in-64 complete-session samples are not exact CPU, total lock hold/acquisition cost, or a removable budget. Perturbation remains unresolved after exclusions. Any future out-of-lock owner notification must keep acceptance checks, FIFO insertion and producer/owner reference publication under `queue_lock`, acquire its target lifetime reference under admission-close protection, and have close/drain join all notification tails before teardown. |
| 156 | Lifetime-pinned owner notification outside admission lock | **native fixed comparison declined / removed** | Development/native concurrent lifetime and loaded GC/suspend/fault gates pass, but that ownership proof did not promote the candidate. The first fixed pilot was unusable: 71/72 comparisons were excluded while a competing host workload remained active, leaving zero usable primary pairs and no performance judgment. After that workload ended, a separately declared native-host pilot passed 288 arm oracles but still missed its declared retention screen: persistent NVMe5 n7 +1.63%, family interval -6.43..+10.39%, adjusted sign p1, below the +3% floor and minimum n9; SATA n11 -2.18% and fast n11 -0.09% remained inconclusive, with seven exclusions without replacement. Exploratory p95/CPU directions do not qualify retention and no lower-WRITE benefit was proved. Qualified production and helpers were restored. Any future revisit must preserve the ID155 admission-close lifetime pin/join rule; that is a requirement for a future variant, not current production behavior. |
| 157 | Resolve pack/submit ancestry to actual lower-backend work | **native diagnostic / model sensitivity next** | Three fixed owned pairs/six arm oracles and complete gates pass; source/ELF/live-section checks resolve 1,019 owner samples. 165 include null_blk backend allocation/initialization/locking, versus 39 dm_io-only and 815 other. Those observed null_blk allocation/initialization/locking frames are lower-backend work, not a pure swapz packing budget. Broad pack/stage labels and cycle-weighted samples are not exact CPU; all rows NOISY on 16% raw-repeat drift. Do not infer RAM-bandwidth saturation or reopen rejected direct BIO from this evidence alone. Next matched both-arm full-backing materialization control with unchanged C and separate protocol history. |
| 158 | Matched both-arm RAM-backing materialization sensitivity | **native model study complete; no product change** | Eight fixed rounds/16 blocks/192 arm oracles pass with unchanged C. Materializing both raw and swapz backing yields persistent normalized +9.07%, family interval +0.78..+18.04%, but n5<7 and adjusted sign p0.1875 fail direction criteria. SATA +1.10% and fast -0.19% remain inconclusive. Four exclusions without replacement; cross-condition raw changes are outcomes, not exclusion criteria. Exploratory absolute swapz service +6.48% NVMe/+2.13% SATA, fast unchanged with p99 trade-off. Preserve cold qualification/history: this is a model-sensitivity study, not product promotion, physical-NVMe fidelity, or evidence of RAM-bandwidth saturation. Next isolate backend mechanism/residual C. |
| 159 | Both-arm serial lower-queue sensitivity on SATA/NVMe5 | **superseded before owner measurement / removed from make test** | The depth-one-both-arms control would mostly remove raw concurrency while production swapz is already K=1, and mixed READs would be penalized asymmetrically because raw reaches lower storage while swapz often serves cached reads. It therefore cannot answer whether swapz can use additional lower-WRITE concurrency. Remove the four permanent pairs and report plumbing before relying on an owner result; preserve only this design lesson. |
| 160 | Independent-target striped replay, N=1/2/4 | **development experiments expanded / owner data pending** | Use one page/lane-owned persistent QD32 trace, partitioned exactly by logical page modulo N across N independent existing K=1 swapz targets and N matched raw lower devices. Aggregate offered QD stays 32. Each lower receives 1/N of model bandwidth and 1/N of aggregate queue capacity; raw and swapz use identical mapping. Measurement starts are synchronized after every native lane completes warmup. Record common-interval throughput, lower bytes/requests, per-stripe p99/depth, plus an observational all-lower sampler for simultaneous WRITE-active swapz backings. NVMe5 is primary; SATA is secondary. Five counterordered rounds per N are the default for the selected `*-stripes` fast-test scenario. Separate opt-in fast-model sustained WRITE QD4/QD8 trials now reuse the same exact N=1/2/4 split and 80 MiB/s aggregate model, with QD/N per target; their ratios and request savings are separate cohorts, not pooled with QD32 mixed. The ordinary fast_test SUBMITTER_PREPARE=0 control pins the existing module switch to compare async placement without changing product C, and records an optional browser-load profile without waiving noise gates. The lone-RAW production optimization is retired by ID161: an empty accepted queue is not proof that the next WRITE cannot share the extent, and the old-PC owner result showed no service gain. Interpret striping only as a lower-service overlap diagnostic: splitting QD across targets also splits packing opportunity (N=4 at aggregate QD4 is QD1 per target), so target-count scaling alone cannot model an in-target K>1 packer. The experiment never changes kernel C or qualification history and must observe actual simultaneous swapz lower service before K>1/sharded-authority work is reopened. If normalized swapz/raw WRITE service does not materially improve with N despite observed overlap, drop the multi-WRITE hypothesis. Pre-run review (`0ae549b`) found three defects CI cannot exercise: every swapz arm would be rejected by io-replay's owned-target check (`SWAPZ-STRIPE-*` UUID instead of `SWAPZ-TEST-<16 hex>`); N=2/4 mappings stayed 8192 sectors although each stripe's workload is 1024/N pages, which the exact-size check rejects; and the start gate released stripes before swapz-only `dmsetup` epoch/status subprocesses, staggering swapz N>1 starts and biasing the common-interval throughput against striping. Fixed: SWAPZ-TEST UUIDs, mapping size from the child manifests, and release immediately before timed GO after all pre-measurement snapshots; rootless contracts pin all three. |
| 161 | Learned isolated-singleton RAW representation | **5 old-PC owner-refuted / removed** | Source `8c8f8c6233d2` passed all five `make test` stages. ID161 selected 5,372 pages across the full session, with no cancellations or multi-record mistakes. Timed Fast QD1 RAW useful WRITE was 14.48 MB/s versus same-pair raw 16.59 (−12.7%), with exactly 4,096 lower WRITE requests and identical 16,777,216 lower bytes; p99 worsened to 0.437 vs 0.383 ms. Timed LZ4 work was zero yet the candidate did not outperform the ordinary async 14.67 MB/s from another pair. Skipping compression does not remove fixed ordered/window/commit overhead. Remove experimental code, counters, qualification pair, parser and reporting; Git retains evidence. Reopen only with a different singleton completion path that preserves generation/CRC/fence ownership and demonstrates service benefit. |
| 162 | Work-conserving early-hand threshold A/B | **2 selector retained / hand16 pilot has no established service gain** | Fast sustained QD32 asynchronous preparation often closes via the eight-record hand, fragmenting windows and lower requests versus sync. Same-source two-host observations support that scheduling signature, but host CPU pressure confounds historical throughput changes. Keep K=1, SWZ, the four-record floor and immutable completion ownership. `HAND_RECORDS=8|16|64` (default 8) is an opt-in ordinary retained-async `make fast_test` null_blk-only control; nondefault thresholds are rejected for synchronous/non-retained or physical targets and checked in DM status. Compare Fast/Serial QD32 with submitter on/off and controlled host load: useful throughput/p99, lower bytes/requests, windows/pages per request, early hand closes, accepted-work idle, ready-run wait, byte oracle and screening. The 64 threshold does not guarantee a 64-record physical run: other closes remain valid. The fixed production-stack old-PC hand8/16/16/8 pilot on `99fa60bb` passes all 32 byte oracles: screened fast-QD32 requests -18.0%, bytes -1.74%, normalized useful WRITE -0.5% (95% CI -10.7..+10.8%), accepted-work idle +69.8%. Hand16 reduced window fragmentation and requests but did not establish the required useful-service gain and raised accepted-work idle. Keep eight; primary service benefit and all guard bounds are unproved. Threshold64 and submitter-off interactions remain separate untested questions. No promotion without exact-source owner `make test`. |
| 163 | Four-record async detachment without queued preparation | **fixed old-PC pilot did not justify retention / removed** | On qualified b336754e C, change only the async-detach count gate from >4 to >=4. Prespecified control/candidate/candidate/control, two repeats on fast QD8/QD4/mixed and serial QD8: 32 byte-exact raw/swapz pairs; six screened exclusions without replacement. Two usable QD8 pairs give normalized useful WRITE +0.4% (95% CI -37.8..+61.9%), below the 5% practical criterion; QD4 point service -4.4% and WRITE p99 +22.8% do not meet guards, with broad intervals. All-observation diagnostics show QD8 synchronous four-record commits 790 -> 0, windows 968 -> 828 and requests 975.5 -> 836.5, but idle 21.5 -> 77.8 ms. Activity and packing improve without an established service gain. Restore the production strict `>4` predicate exactly; do not infer equivalence or causal regression, or keep an unsupported selector. |
| 164 | Bounded early acknowledgement from staging | **0 unapproved architecture proposal / not implemented** | Early acknowledgement would change the storage-success contract: Linux v7.0 backing-swap WRITE failure re-dirties/retains the folio, so reporting success before lower success removes that kernel recovery path. Production therefore remains lower-I/O-confirmed acknowledgement. Any future design requires explicit owner approval and must never early-ack a FUA WRITE or complete PREFLUSH before all earlier acknowledged generations reach lower success; keep every acknowledged staged generation bounded and independently owned after its upper BIO is gone; prevent overwrite, DISCARD, or late lower completion from resurrecting stale generations; never let READ expose stale lower data; drain or otherwise preserve acknowledged unwritten generations across suspend, drain, and table removal; and define the contract for lower failure after ACK. No implementation or opt-in is authorized by this row. |
| 165 | Dispatch older ready prefix before submitter-owner deferral | **5 fixed old-PC pilot rejected / removed** | One helper flushes an already-staged >=4-record work-conserving prefix on an idle K=1 lane, after FIFO handback and without touching the active head. Fixed control/candidate/candidate/control, two repeats on fast QD8/QD32/mixed and serial QD8; all 32 pairs byte-exact. Screened normalized primary fast-QD8 service -3.7% (unadjusted paired 95% CI -6.2..-1.2%). The extra prefix dispatch split useful aggregation: fast-QD32 lower-WRITE requests +10.0% and serial-QD8 +43.4% violate the 5% request guard. Existing early-hand counters prove engagement, not a removable budget. Restore C exactly; a submitter deferral is not automatically removable idle or a proven lifecycle bug. Reopen only for a distinct measured mechanism that preserves useful aggregation. |
| 166 | Suppress submitter-release wakes behind an active visible FIFO head | **5 fixed old-PC pilot unpromising / removed** | Peek the current incoming head under queue_lock after release, preserving wakes for empty incoming; pair suppression with a locked worker ownership recheck before handback to prevent a lost wake. Actual C interleaving probe passes and rejects a missing-recheck mutant. Fixed control/candidate/candidate/control, two repeats on five scenarios: all 40 raw/swapz pairs byte-exact. Four screened primary fast-QD32 comparisons give normalized useful WRITE -0.2% (95% CI -6.6..+6.5%) and owner deferrals +1.4% (-6.1..+9.6%); no established service/mechanism gain. Restore C exactly. Empty incoming/private-FIFO wake suppression was explicitly not tested; reopening needs a distinct measured mechanism and complete wake proof. |
| 167 | Suppress submitter-release wakes for a private ordered FIFO | **5 fixed old-PC pilot unpromising / removed** | Extend ID166 to wake only a nonempty ready incoming head, suppressing empty/private-FIFO wakes too; keep the locked ownership recheck and prove release/handback cases plus a rejecting mutant. Fixed control/candidate/candidate/control, two repeats on five scenarios; all 40 pairs byte-exact. Four screened primary fast-QD32 pairs give normalized useful WRITE -2.1% (95% CI -5.0..+0.8%) and deferrals -4.5% (-11.1..+2.6%), missing the +5% service/-25% deferral targets. Restore C exactly. Both suppression variants lack service/deferral evidence; do not add another wake predicate without a specifically attributed unnecessary-wake population, a distinct prospective mechanism and complete progress proof. |
| 168 | Submitter on/off placement on the two-core old PC | **5 QD4 primary missed / default unchanged** | Same-source on/off/off/on, two repeats on five medium scenarios, production compression fixed on, all 40 pairs byte-exact. Background/submitter raw-normalized QD4 +0.8% (95% CI -0.8..+2.5%) misses the 5% floor; QD8 secondary +4.4% (+2.8..+6.1%) with producer/lower-WRITE overlap motivates ID169, not a global disable. Mixed/latency guards remained unresolved, so the global submitter-off mode was not promoted. |
| 169 | Use producer preparation during active lower WRITE service | **4 promoted / x86 and ARM64 owner PASS (`9123b811`, `7ff94fd4`); i3 pending** | Owner reports (x86 `5a66c7ec`, ARM64 `3faa3914`) pass all stages with the frozen guard; Fast QD8 +36.2/+27.8% and Fast mixed +88.7/+14.4% with lower bytes/requests saved. Same-run evidence is directional, not a causal A/B. Bypass only the submitter resource claim while `lower_write_active`; retain idle-lane submitters, existing fallback ownership and module default. Actual claim-body resource/I/O-state checks pass and reject a missing-guard mutant. After the 40-pair hypothesis-generating pilot, the exact C was frozen for eight independent ABBA cycles on QD8/QD32/mixed: all 192 raw/swapz pairs were byte-exact and actor-conserved. Primary QD8 has 24 usable comparisons over eight cycles: normalized useful WRITE +5.61% (cycle-cluster 95% CI +3.83..+7.41%), sign-flip p=0.0078125; QD8/QD32 guards pass. The fixed shorter mixed cohort has only 11 comparisons/five cycles, below the 12/six minimum, with service and p99 bounds unresolved; 46 screened observations were excluded without replacement, with no pilot pooling or extension. At confirmation close the candidate was restored because the primary benefit alone did not authorize retention, and the mixed result must not be read as a regression or portable-host claim. Owner decision 2026-11-01 later promoted that same frozen guard to production; unresolved mixed service/lower-I/O/p99 bounds became exact-source owner-run watchpoints. Reject again if those owner mixed watchpoints regress beyond their guards. |
| 170 | Longer mixed development traces for guard measurement | **2 harness validated / no product-policy change** | `MIXED_OPS=65536` extends ordinary mixed-only `make fast_test` streams fourfold; default/official traces remain 16384. Reject WRITE-only, stripe and calibration misuse before privilege. Actual rootless plans preserve the original exact trace prefix and final-image oracle; two loaded control pairs pass 65536 ops per arm. Quiet/raw-drift screens stay unchanged; new duration is a separate cohort and cannot relabel or pool ID169's completed evidence. The nested rootless suite needs a bounded 90s allowance on this CPU (~44s measured); loaded watchdogs are unchanged. Fresh idle process observations show possible agent/app interference but do not attribute historical exclusions. A prospective mixed guard protocol remains required. |
| 171 | Release submitter snapshot before optional compression | **5 unconditional pilot rejected / removed** | Fixed four-block old-PC ABBA with two repeats on five scenarios: all 40 pairs byte-exact and actor-conserved; 16 screened exclusions, no replacements. Only two usable primary QD4 comparisons: normalized WRITE +4.14% (unadjusted 95% CI -8.17..+18.11%), below 5%; lower bytes +2.73% exceeds 1% guard. Descriptor-poison/ASan/UBSan probes and four rejecting mutants support bounded two-reference ownership, not production qualification. RAW-before-ready/late discards engage and deferrals fall, but neither justifies extra I/O. A report-only remote advance interrupted before final control; source equivalence was proved before administratively completing that one unstarted block without changing the sample or criteria. Control C restored; no retention. Its zero asynchronous-LZ4 EWMA observation motivated ID172's estimator-coverage repair; it does not retain this prototype. |
| 172 | Include completed asynchronous LZ4 cost in adaptive EWMA | **1 owner-qualified (`bb665730`, report `48a1580f`)** | ID171 controls report zero EWMA despite 4096 submitter compressions and 25.6–27.0 ms LZ4 wall. Publish a per-page LZ4 elapsed delta from both asynchronous owners before READY, then let only the ordered owner update the existing estimator for READY_COMPRESSED/READY_RAW. Ignore mutable/unready/error metadata and preserve zero/unknown samples. Keep original submitter lifetime, slot references, RAW policy, encodings and K=1. Actual-body writer/observer tests reject cumulative-time/missing-guard mutants. Three loaded validation pairs are byte-exact and drained with zero inline work: QD4/QD8/mixed EWMAs 7284/5222/4938 ns. Kernel DWARF size remains 8256 bytes per slot. Full owner make test passes five stages; all 66 recorded swapz WRITE arms retain required compression and positive EWMA. Resource-pressure startup under memory.high extends the complete run to 35m59s without relaxed limits. Seven this-host PASS reports/74 history points; low-QD fast and SATA/NVMe service gaps remain. This repairs a missing input, not an attributed throughput gain.  |
| 173 | Acquire READY after losing the RAW-selection race | **2 implemented; owner run BLOCKED at raw pressure control (`3ef72d9f`, report `fd5ed47e`)** | Linux conditional RMW failure is unordered. Reacquire stable READY after losing PREPARING-to-RAW cmpxchg; the consumer reference prevents reuse. Ordinary READY/RAW-win paths keep one acquire, with no wait, ownership, codec or depth change. Old header and compiled relaxed-reread mutant fail; fixed native threaded reuse and ASan/UBSan pass. Owner stages 1–4 and pre-pressure loaded checks pass; ID36 raw startup times out at 280s in memory.high charging. Preserve BLOCKED; stop only test-owned pressure after terminal failure to allow cleanup, no retry or relaxed gate. All 66 recorded WRITE arms keep compression on, positive EWMA and drained gauges. Partial fast QD4/8/32 normalized service declines 5/5/7% are watchpoints, not causal estimates; history excludes this run. |
| 174 | Per-device-class product goals | **1 owner-adopted acceptance criteria / descriptive scorecard** | Compression can only shorten service that waits on device bandwidth or queueing. Device-bound classes (serial/fast mixed, serial QD4/8/32, fast QD8/32, SD card, SATA) must beat raw useful WRITE and save lower WRITE bytes and requests. Latency-bound (serial/fast QD1, fast QD4) and host-bound (NVMe Gen4/Gen5 mixed) classes are guards within 5% of raw that must not add lower WRITE work. Linux v7.0 swap-out to a DM target is asynchronous, so closed-loop QD1/QD4 rows are guards, not targets. `tests/tools/product_goals.py` classifies once for the report scorecard (`benchmarks.goal_scorecard`) and the history plots. Descriptive only: never a gate. Stop polishing guard rows that already sit at their single-lane ceiling (i7 QD4 measured +5.9%/-2.2% against a computed ~+7% ceiling). |
| 175 | Idle-lane submitter dispatch | **4 implemented / x86 and ARM64 owner PASS; i3 QD1 evidence pending** | Owner reports for `9123b811` (x86) and `7ff94fd4` (ARM64) pass all stages; 4032 of 4096 timed QD1 writes dispatched from the submitter on both hosts, and Serial/Fast QD1 stay inside the 5% guard (x86 -1.7/-2.6%, ARM64 -0.4/-4.7%). Not finished: its stated target is the i3 QD1 (-25%), which still needs an exact-source i3 report. Design: a QD1 write paid two extra thread hops (submitter to ordered worker, then lower completion to worker); the measured per-write overhead tracked each host's own host-side time (about 6/21/86 us on i7/ARM/i3). Remove the submit hop: when a learned isolated stream (`singleton_fast_close`) admits a lone plain WRITE with an idle lower lane, the submitting task trylocks the ordered-domain mutex, prepares the page in its ID150 lane, re-proves eligibility (nonzero READY representation, no staged/in-flight/queued work, open-segment placement with no GC or segment-recycle DISCARD) and detaches the one-record K=1 run itself. `->map` never waits: lower BIOs only queue on `current->bio_list`; an undetached dispatch fails closed. Completion, publication and ACK stay with the ordered worker; a dispatched run is ACKed after the worker releases ownership so the next closed-loop write can dispatch again. No new queue, slot, lane, timer, format or module parameter. Telemetry: `submitter_dispatches`, `submitter_dispatch_declines`. Reject if loaded lifecycle/fault/suspend/ID36 gates fail or i3 QD1 does not improve with positive dispatches. Generalizing it to append into an active window is ID180, not this row. |
| 176 | Two lower-WRITE lanes behind one authority | **6 deprioritized, not refuted** | Busy fractions (38-76%) bound what any pipelining can recover, but they do not show that a second lane would have work: ID178 must first show how often a successor run exists before the active lower WRITE finishes. The ID160 screen (`make fast_test SCENARIOS=nvme5-stripes,sata-stripes` on the quiet x86) stays descriptive: a positive N=2 result shows that more independent execution can raise normalized service, but stripes change owners, batching domains and targets together, so it cannot identify owner serialization or prove in-target K=2. The 2026-11-01 x86 five-repeat screen retained SATA N=1 and N=4 (5/5 each): normalized swapz/raw WRITE was 1.2043 and 1.6147 (+34.1% N=1→N=4), with four simultaneous lower devices observed in every N=4 pair. Lower-WRITE savings fell from 31.15% to 27.65% bytes and 93.29% to 83.88% requests. SATA N=2 was excluded for 10.9% raw-control spread; every NVMe5 stripe count was excluded for 10.9–30.0% spread. Treat this as evidence that independent SATA-model targets can raise aggregate service at a measurable lower-I/O cost; it does not identify single-owner serialization. The first combined-model plan setup also exposed duplicate generation of the shared mixed trace; the builder now prepares each workload once and its actual-plan regression covers both models. The fixed run artifact is preserved locally at `build/tests/fast-test/archive/id160-stripes-265a39e1-dirty.json` (SHA-256 `d3f9a5a37e850245995e48e7101e25ae12e522b68202316cc81d3021fc62349d`); tooling was dirty and the run is not qualification history. Reopen design only if ID178/ID179 show the single-lane pipeline routinely has a sealed successor before the active lower WRITE completes, with lower-byte/request savings and READ p99 preserved. Design prerequisite unchanged: the authority keeps one paused batch group (`batch_pending`, `batch_segment`, `batch_first_sequence`, `batch_hashes` are singletons), so a second in-flight run needs a second paused group or segment-disjoint ownership, plus FIFO publication and same-page fences. |
| 177 | Representative swap content | **Analyzer and matched-cohort tooling implemented; owner sample measurement pending / no product policy change** | The benchmark fixture compresses ~1.43x while reported LZ4 ratios on real swap are ~1.5-2.6x. `make fast_test` now accepts an owner-supplied file of 128..8192 concatenated 4 KiB pages through `CONTENT=representative ANON_PAGE_SAMPLE=/private/path/pages.bin`; it copies the sample into a private temporary plan, runs the aggregate-only offline analyzer, then gives the same fixture and trace to raw and swapz arms. The analyzer models production's predictor-first direct adoption, fallback/packing route, acceleration defaults and 64-page extent planner, and reports aggregate content/route/planner statistics without page bytes, per-page records, hashes or source paths. Native tests cover aggregate-only output, representative plan identity and symlink refusal. The owner sample and matched hardware cohort have not yet been measured. This remains offline emulation: no swapon, physical partition, policy change or qualification claim. |
| 178 | Lower-lane gap attribution (passive) | **4 owner PASS on x86 + ARM64 (`1a527d46`; reports `fbd6c1f2`, `95430926`) / decision evidence consumed by ID181** | Observational only; no policy, wait, queue, allocation, format or ACK-timing change. Implemented by external agents (`6170f59d`, `5329aae3`, `2787ffa6`, `f6599bb8`); lead review fixed: engine observer hooks fired during GC compaction and counted `lane_gap_invalid` (which fails every timed session closed), an unpaired submission left an older predecessor valid, a profile_epoch race on a synchronous run counted as invalid, and foreign WRITEs between a predecessor's completion and publication went unnoticed; t3 was restored to the seal start (the second agent had moved it after prepare, folding plan/pack/CRC into staged/held), and accounting now follows the lower submission. Per K=1 gap (predecessor lower completion t0 → successor lower submit t4) record an exact partition: completion→owner observes (t0..t1), publication (t1..t2), then for the successor run: no admitted work (t2..a), admitted but not yet ordered-owned (a..s), staged and held before sealing (s..t3), seal = plan/stage/pack/CRC/submit (t3..t4), with marks clamped so the parts sum exactly to the gap; gaps overlapped by any other lower WRITE (GC, single-page RAW) are foreign. Report paired/foreign/unpaired coverage, admitted and ordered-owned successor histograms at t0 (0, 1, 2-3, 4-7, 8-15, 16+), publication→`bio_endio` dwell bins for deferred/immediate ACKs, owner READ service inside measured gaps (annotation, not a part), and `host_cpu` on SATA/NVMe4/NVMe5/fast-mixed arms. [Work order](handoff/lane-gap-diagnostics.md). Decision rules after both-host owner reports: staged-held + seal dominant with a successor commonly present at t0 → ID179; admitted-not-owned dominant → owner pickup/wake/READ-ahead path; no-work dominant with no successor at t0 → upper round trip (ACK dwell, ID164 early ACK, or K=2 with split runs); completion/publication dominant → shorten finalization. |
| 179 | Seal-ahead at K=1 | **6 conditional on ID178** | Candidate only if ID178 shows a successor is commonly present by lower completion but sealed after it. Seal (plan, pack, CRC) the successor while the active lower WRITE is in flight and submit it at completion, keeping one lower WRITE in flight and one publication authority. Not a second buffer: the sealed successor must preserve FIFO publication, reservation ownership, same-page fences, failure rollback of both runs, GC boundaries and suspend/drain, while the authority's paused batch group is a singleton. Must keep lower bytes/requests and READ p99 within guards. |
| 181 | Successor-first dispatch (A) and publication-time ACK handoff (B) | **REJECTED / REMOVED: x86 no promotion, ARM64 production PASS with selectors disabled** | Default-off owned-null_blk experiment. Fixed x86 factorial at `6730ef7c` found no promotable policy. On exact source `705589f`, owner `make test` passed 5/5 (report `c56dfdc`); the repeat four-block factorial at the report-only descendant `c56dfdc` found no >=10% normalized useful-WRITE gain: A/B/AB vs control SATA -1.3/-2.7/-2.6%, fast mixed +0.1/+0.2/+0.8%, fast QD4 -0.8/+0.4/-1.1%, QD8 -1.7/-2.0/-4.0%. SATA A/AB added lower WRITE requests; fast QD8 A added +17.7% (CI +4.3..+32.7%). NVMe4/5 were excluded by fixed raw-spread screens (18.8/28.7%). On 2026-11-02, the ARM64 owner `make test` passed all five stages for exact source `604866c1` (report `e760e91`, AArch64 host identity); this qualifies lifecycle/reporting, not ID181 performance. Owner decision 2026-11-02: retire the A/B/AB development policy without an ARM64 factorial; x86's fixed screening rules show no generally promotable result, and ARM64 default-off production qualifies. Remove selector fields, policy branches, counters, factorial tooling and dedicated tests while retaining shared ID143/ID175 completion handoff. ARM64 mechanism-specific performance remains untested; do not misstate the x86 results as cross-host refutation. A cleaned source requires fresh x86 and ARM64 owner qualification. ID162 remains separate; ID179/ID176/ID164/ID180 stay deferred. |
| 180 | Submitter append to an active window; cached-READ submitter bypass | **0 deferred / not justified** | Appending ID175-style into an open window under load adds FIFO and concurrency hazards, and the submitter mostly fails `mutex_trylock()` while the worker owns the domain. Serving cached READs in submitter context would bypass the owner, but the x86 READ p99 loss includes lookup, decode, verification, copy, locking and scheduling, not pure queueing. Reconsider only if ID178 shows admission→owner or owner READ service as a dominant, avoidable part of lane idle. |

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

**ID178 instrumentation cost hypothesis (2026-11-01):** ARM64 cross-report
fast-mixed service fell from roughly 71.9 to 69.0 MB/s after ID178, with
suspected per-ACK time/atomic overhead; this is not a same-source controlled
instrumentation A/B. ACK delivery now samples one timestamp per owned delivery
cohort and accumulates dwell bins within that existing loop before a bounded
atomic flush, removing both per-BIO clock reads and per-BIO telemetry atomics
without changing acceptance or ACK timing. Direct unbatched completion keeps
its exact fallback clock. Treat ACK-dwell values across this instrumentation
boundary as comparable only within the bounded delivery-loop timestamp error.
Validate ARM64 performance prospectively; do not claim the 4-6% difference is
proven ID178 overhead.

## Immediate work queue

**Current round (2026-11-02, ID181 retirement and clean baseline).**
Owner decision: retire ID181 as a general production candidate without an
ARM64 factorial. The fixed x86 counterbalanced factorial showed no A/B/AB
policy meeting the >=10% normalized useful-WRITE objective, with added
lower-I/O requests in selected arms. This is failed promotion evidence, not
proof of universal regression. ARM64 already passed all five owner stages
with ID181 disabled on exact source `604866c1` (report `e760e91`);
x86 passed exact source `705589f` (report `c56dfdc`). Neither
qualification covers the cleaned removal commit. Preserve the historical
ID181 evidence above, and remove its default-off code, selectors, counters,
factorial tools and dedicated tests. Retain the production ID143/ID175
completion handoff and all other accepted scheduling/authority semantics.

Next work, in order:

1. Run CI on the narrow ID181 cleanup. Then run official owner `make test`
   on both x86 and ARM64 against the **same exact cleaned source SHA**.
   Both full five-stage results and their reports must pass before this
   source is a newly qualified baseline; do not infer PASS from rootless
   checks, older host reports or CI alone.
2. ID177: use the existing `CONTENT=representative` owner-supplied offline
   anonymous-page sampling and aggregate-only analyzer on the available
   host. Compare the same fixture/trace controls; never collect process
   RAM, enable swap, or publish raw representative page data.
3. Diagnose Fast QD4 (ARM64 -10.5% versus x86 +5.6% on the latest
   owner-host observations) before any policy change. Measure admission
   to ordered-owner service, preparation/deferral, window width,
   pages/lower request, ACK and completion delays, host CPU and lower
   service. Cross-host results are descriptive, not causal.
4. Collect ID175/ID169 exact-host evidence on the actual i3 when it is
   available. Preserve both mechanisms and their mixed/QD8 watchpoints.
5. Keep ID179, ID176, ID180 and ID164 closed/deferred. ID179 is weaker
   because measured seal time is small and earlier ID181 dispatch showed
   no material service win. ID162's nondefault hand threshold is a
   **separate possible cleanup**; do not remove it in this commit.

**Previous round (owner plan, after `3478aec`).** Adopted the ID174
per-device-class goals, promoted ID169 and implemented ID175; both now pass
on x86 and ARM64, with the i3 report outstanding.

The old-PC source `3ef72d9f67d6` passed native acquire-race coverage but its owner
`make test` report `fd5ed47e398e` is **BLOCKED at ID36**: the raw control
hit its existing 280-second limit before swapz ran under pressure. Read-only
stack evidence identifies filemap faults and `memory.high` throttling in raw
startup, not a proven swapz I/O stall. After the preserved failure, operator
intervention created this fixture's `pressure.stop` barrier to free ordinary
teardown. The narrow follow-up makes an already-failed owned ID36 pair signal
only its proven private stop barrier **before** starting safe device cleanup;
on success, full pressure remains active through teardown. Rootless simulation
covers failure-only signalling and symlink/unproven-path rejection. This does
not cure the raw startup slowdown, establish unattended privileged cleanup, or
qualify source/performance. Recheck unattended failure teardown on the owner
host, then investigate pre-replay harness fault charging without preloading
away the pressure test or extending its 280/840/960-second bounds.

ARM64 owner report `e73614c` (source `6c33294`, production delta64 +
DELTA64_SHUF8 + LZ4 everywhere) passed all five stages; the loaded delta64
positive path passed its hard gate, and its counts are now persisted as
`PASS_LOADED_DELTA64_POSITIVE`. The fast QD4 change from -25.7% (report
`9d30bf1`) to -12.4%/-12.9% is host load, not code: QD4 runs the sync4 path
with zero deferred ACKs, and host busy fell from 0.52-0.58 to 0.05-0.13 while
sync4 lower time per window fell 191-194 -> 179 us and the reissue gap
54-56 -> 40-41 us. A fast QD4 wave is 179 us lower WRITE + 40 us reissue +
3 us non-I/O; raw is bandwidth-capped at 84 MB/s, so a zero-gap K=1 ceiling is
about 90 MB/s (+7%) and parity needs a gap of 13 us or less. QD1 is latency-bound
(22 MB/s versus the 84 MB/s cap), so compression cannot win it while success
is tied to lower completion. On the SATA/NVMe4/NVMe5 envelopes (QD32 mixed,
compression 1.40-1.44x), the K=1 lane is busy only 64/47/37%, and 51-66 ms per
session pass with the lane idle and no admitted WRITE. Raw NVMe5 (538 MB/s)
below raw NVMe4 (612 MB/s) shows the raw arm is host-bound on this 7-vCPU VM.
The striped (ID160) and hand-threshold (ID162) experiments remain the next measurements.

The follow-up old-PC QD4 reissue diagnostic produced no valid causal timing
partition: the final raw-syscall observer lost 22,281 events, missed independent
operation/lower-request counts, failed host screening and exceeded its 10%
descriptive perturbation screen. Earlier attempts selected the wrong replay
engine and then silent named syscall tracepoints. All final benchmark byte
oracles passed, but these observations cannot select a production optimization.
The broad sync4 reissue timer includes acknowledgment, writer reissue,
admission/preparation and retention. Preserve qualified C; first prove bounded,
complete capture before attributing that whole interval to removable idle.


The old-PC owner run at `09e1cfaa` exposed zero fault-session handoffs.
Inspection found completion handoff using the eight-record dispatch constant,
although its contract requires four published BIOs. The native actual-body
test masked this with a private four-record definition of that dispatch
constant. Restore a dedicated four-BIO completion floor and compile actual
production constants in the regression. Source `b336754e3acb` passed all five
old-PC owner stages (report `8b67a9425025`), observing 16 live handoffs, eight
fault-session handoffs and 16,512 exact successful WRITEs across suspend/drain.
ID36 passed with eight CPU-pressure workers and 23,587 memory.high events.
Remote fixture changes independently permit zero fault-session handoffs while
preserving positive live suspend/drain activity. This qualifies the repair;
it does not establish a causal performance improvement from the threshold.
The fast async mixed arm still records 252 ms accepted-work lower idle,
including 188 ms undersized-batch attribution, and zero K=1 ready-run wait.
It performs no delta64 attempts on the medium fixture. Investigate the small-
batch/owner path before reopening concurrency or blaming delta64 for this
workload's service deficit. The separate five-pair positive-fixture rescue A/B
saves 68.5% lower WRITE bytes (95% CI 67.9..69.2% reduction); useful WRITE
changes +13.1% (CI -3.4..+29.7%), so throughput improvement remains unresolved.

The receiving x86 baseline and ID151 input-copy telemetry are owner-qualified
on modern x86 source `545defa8` (report `3465b4c08987`). The other x86 host passed
on `61739796` (report `2a40d0973839`); its identity/history stay separate. These
are x86 correctness results, not ARM qualification or universal performance.
ID149 direct BIO and ID152 API-based LZ4 state reuse are removed after fixed
pilots did not justify retention. Production remains stateless LZ4 with the
existing bounded submitter policy. ID152's fixed comparison recorded a positive
current-policy persistent-NVMe5 submitter direction and scoped guard/resource
trade-offs; it does not establish a gain on every storage/QD/content arm.

1. The reviewer's ordered sequence is now dispositioned through #3: ID156's
   first fixed pilot was unusable (71/72 exclusions) under the competing host
   workload. After that workload ended, a separately declared native-host
   comparison still missed its retention screen, and qualified production was
   restored. Keep the two studies distinct and do not repeat the same variant
   without a new measured opportunity and prospective plan. Any revisit must
   preserve the ID155 admission-close lifetime pin/join requirement; it is not
   current production behavior.
   ID157 separates null_blk backing allocation from apparent pack/submit
   ancestry. ID158 completed matched both-arm backing sensitivity with no
   product-source change. Profile the backend mechanism and residual owner
   operation before selecting further C work; preserve the canonical protocol.
2. Before timing a candidate, fix source order, samples, matched inputs,
   primary family, practical floor and exclusions. Use service and p95/p99,
   independent lower bytes/requests, GC and resource costs together. Require
   exact-source owner qualification for a retained production change.
3. Any admission measurement must separate lock wait/hold wall from CPU and
   quantify its instrumentation cost before selecting a production C change.
   Preserve exact lower-success/failure and suspend/drain behavior.
4. A custom small-table 4 KiB encoder remains unimplemented; ID152 tested an
   exported-API route, not that encoder. Reopen codec work only for a materially
   new mechanism with stronger measured end-to-end opportunity; do not repeat
   the same state-reuse variant or repeatedly sample it until significance
   appears. Never merge unqualified trials into host history.


The nine-idea review now has direct evidence for first-window lead (ID140)
and mixed barrier sensitivity (ID141); sleep/spin remains the unpromising
ID137 pilot. ID142 identifies ACK-loop interference, and the bounded ID143 handoff is now
qualified with a measured throughput/I/O trade-off. The remaining continuous
NVMe deficit needs fresh attribution; it is not explained by wave barriers. ID144 observes
completion-CPU locality without establishing causality; ID145 counter padding did
not justify retention. A future completion-delivery experiment must first audit
callback lifetime, CPU-hotplug fallback and drain ownership; these observations
do not authorize a cached-READ admission shortcut. ID146 locates the observed
wakeup path but its probe cost is too high for production timing. ID147 READ
notification deferral almost never reached the helper and is removed; entering
a deferred list is not proof of offload. A renewed candidate must explicitly
cover synchronous READ waits and demonstrate actual helper delivery. Selected-wait idle,
accepted post-lower delay and deferred-ACK wall have different scopes and may
overlap other work; never sum them into a CPU total or call the first the whole
device-idle budget. ID150 now tests submitter compression as one bounded candidate; lockless admission remains
conditional and is not a consequence of summing concurrent lock waits.

A dm-linear arm would be a DM calibration reference, not an exact unavoidable
overhead budget: DM has target-specific fast paths, while swapz owns clones,
ordering and completion state. Direct BIO submission and polling are separate
experiments. Upstream Linux v7.0 null_blk polling bypasses its timer completion
path, so enabling it only for swapz would change the device model relative to
raw ([driver source](https://raw.githubusercontent.com/torvalds/linux/v7.0/drivers/block/null_blk/main.c)).
A cached READ in admission requires pinned immutable cache/authority views plus
pending same-page WRITE, GC, DISCARD and fence safety; a generation check alone
is insufficient. Early ACK from staging remains a separate unapproved ID164 architecture
question requiring an explicit owner change to the lower-success publication
and failure contract; it is not authorized as a scheduling optimization.

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
real swap semantics, representative churn and modeled interruption
qualification remain separate release gates. True cold-boot behavior remains
unverified because VMs and intentional host crashes/reboots are excluded.

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

A release or physical-media trial remains blocked until the same pinned source has repeated byte-exact loaded correctness, genuine lower error coverage, sustained GC, bounded resource behavior, acceptable read p95/p99 and CPU/RAM, statistically defensible matched performance, and an independent safety review. Physical-device admission is not part of ordinary make test.

### Owner-requested physical swap-partition smoke — bounded correctness only

**2026-11-02 PHYSICAL CORRECTNESS SMOKE: PASS (HOST-REPORTED;
BOUNDED CORRECTNESS ONLY).** Run
`94e5cd3f2c15d6ff52587d568e8d11f5` executed on bare-metal x86_64
from 09:27:34 to 09:27:52 PST, with qualified production source
`651c35bb5023a69e8a8b42f1113b8a9beaf3c7f6` and helper-policy
commit `841c2bb8c4c4e6b064fe857eaabb976d4c596cdf`. The exact bound
artifact/helper hashes were verified by the operator, and the final
read-only plan admitted active swap with 0 KiB used. All 11 physical
device-roundtrip invocations returned PASS, covering the 128-page
byte-exact baseline, delta64 write/verify, segmented and cross-
representation verification, and THP write/verify plus ordinary verify.
Post-phase mapper identities and status observations passed.

Original Linux swap was restored on /dev/sda4 (8:4, PARTUUID
`7fb9401d-04`): 16777212 KiB, priority -1, and 0 KiB used at the
09:28:27 PST observation. The restored 4096-byte header matched the
original SHA-256
`ace016a7a3ecd22b0aca05946a305aef2113bc50439452756ae68909010f0afe`.
Recovery state was durably COMPLETE; the owned mapper and dm_swapz
module were absent, before/after unrelated DM inventory was identically
empty, the partition marker was absent and the one-use approval remained
consumed. Root-owned evidence remains under
`/var/lib/swapz/physical-recovery/swapz-physical-94e5cd3f2c15d6ff52587d568e8d11f5/`;
`results.json` SHA-256
`da71b3642824b63ecaa7db43e6fb65baf19cfaefa8cc4fbf2b13d075eb893865`.
These device outcomes are operator-reported, not independently read
from that root-owned evidence directory by this GitHub-side review.

The host's journalctl rejected --kernel, so retained dmesg fallback
records were unfiltered. The operator separately examined the exact
run interval and observed only two informational initialization lines,
with no swapz warning/error attributed to this run. Older messages in
the fallback must not be treated as run failures. The earlier physical
attempt `5c4f825bc3bab808e128b2fc66a58f74` remains FAIL with zero
oracle phases, its recovery COMPLETE and its approval consumed; its
evidence has not been rewritten. This PASS does **not** qualify
performance, endurance, broader physical media, or production use.
No additional physical attempt is approved or necessary to establish
this bounded correctness milestone.

**HISTORICAL 2026-11-02 FOLLOW-UP: NORMAL SWAP RESTORED (OWNER-REPORTED).**
The authorized supervised recovery for run
`5c4f825bc3bab808e128b2fc66a58f74` removed only the owned mapper,
unloaded dm_swapz without force, restored the original 4096-byte header
(SHA-256 `ace016a7a3ecd22b0aca05946a305aef2113bc50439452756ae68909010f0afe`),
and reactivated ordinary swap on 8:4 at 16777212 KiB and priority -1.
The recovery state is COMPLETE, the active marker is absent and the
consumption record remains. Post-reactivation usage reached 720900 KiB,
which does not invalidate normal-swap restoration. The original physical
smoke remains FAIL because no oracle phase ran.

The preserved results.json incorrectly records
`restored_swap_verified=false`: the observation path compared against
capacity and priority omitted from the identity-only recovery target.
The durable saved state contains those expected values, and the
independent restoration checks passed as reported. Do not rewrite the
historical results or imply the physical smoke passed. The host did not
support journalctl's --kernel option; unfiltered dmesg included older
error messages predating the 08:15 physical module load. Their cause
remains undetermined, not established as a swapz physical-test failure.
The recovery-coordinator's initial logging-call error occurred before
device operations; a separate read-only verification preceded the
corrected invocation. A post-recovery whole-partition hash was stopped;
the original 4 KiB header was reverified. No further physical smoke is
approved, and zero-used swap would again be required before one.

**HISTORICAL 2026-11-02 RECOVERY INCIDENT — PHYSICAL TESTS HALTED.** An approved
one-use run cleared and SWZ-formatted the selected partition, loaded
dm_swapz, and created the expected 16 MiB mapper. A colon-delimited
dmsetup information row triggered a false identity failure and later a
false mapper-absence result; rmmod failed while the mapper was in use.
The physical mapper and module remain loaded, original swap is inactive,
the saved formatted-header digest is still present on block zero, and
the intact 4096-byte original header backup is retained. No oracle
phase ran. The consumed approval and active recovery marker must remain.
Before ANY further physical test, separately supervise a live recovery
review proving exact device/mapper/UUID/table/lower identity, module
provenance and a matching original backup. No force removal, reboot,
manual header overwrite or standalone recover bypass is approved.
A helper-only parser fix and green CI cannot certify that live recovery
was completed.

The owner authorized one bounded physical correctness round-trip on the active,
zero-used swap partition, with swapoff limited to that exact selected partition.
This remains outside ordinary make test and establishes no performance,
endurance, NAND-lifetime or general physical-media qualification.

**Historical pre-run disposition (2026-11-02): OWNER QUALIFICATION PASS ON 651c35bb;
PHYSICAL RUN STILL BLOCKED BEFORE DESTRUCTIVE WORK.** The latest x86_64
five-stage owner PASS is published by report-only commit e88c3038.
At last inspection the selected normal swap was active with 0 KiB used,
its original size/priority and matching block-zero digest. The first
approved invocation stopped before swapoff because a successful
`dmsetup info -c --noheadings -o name,uuid` returned `No devices found`,
which the helper incorrectly parsed as a malformed mapper row. No swapz
mapping, formatter, module or physical oracle ran; restoration was not
required. The approval for run 5e7d0aa53634b792f5b399cf7ced2d2e is
void and must not be reused. Fix only the empty-inventory parser, add
rootless regressions, then require green current-HEAD CI, a fresh
device-bound one-use verbal approval and a positive read-only plan.
No additional owner `make test` is required if the qualified production
binaries and source-to-HEAD exemption remain valid.

Admission is limited to bare-metal x86_64; the helper must reject VM and
container execution and fail closed if `systemd-detect-virt` is missing or
inconclusive.

The owner-supplied x86_64 five-stage PASS report was inspected from
test_results.json at report commit 74d8521bd2202481b39ce450d519432844dfc4fa.
It qualifies production source fa0875c96a2f401461a2538301c14dff5c691db4 and
publishes the following artifact SHA-256 values:

- swapzctl: c917bfcb064576b84efea07c2fcec693b8199ccbbf78761aec6d626f58dd212a
- dm-swapz.ko: e9001e487e3a86f2404c716f69bb01aa4cc4676f4a5f869201468d1a91850d67
- device-roundtrip: 2bd79246f5524c00ed06752c66b770a6a15532451e981b9a8cb93f9446ec2b8f

All three live artifact files match those hashes. Two earlier same-host x86_64
five-stage PASS reports for source db9e90536551 have the same three hashes.
They are repeated evidence of the same built artifacts, not additional
same-source qualification requirements. A new owner make test is not requested.

The helper policy is being narrowed to require at least one complete latest-
source owner PASS with qualified artifact digests, and to admit earlier
qualifications only when all three hashes match. Post-qualification commits
are limited to the physical helper, its rootless regression, this testing
standard, this roadmap and report-only test_results.json publications. Reject
merges and every other changed path; any production source, oracle C or build
input change requires new owner qualification. Rehash the live artifacts again
immediately before the run and execute only recovery-directory snapshots.

Remove SSH-signature verification and bind the supplied verbal approval text
as a strict, duplicate-key-rejecting JSON record with approval_mode verbal,
reviewer openai-chatgpt-external-reviewer, qualified source, current helper Git
commit and SHA-256, all artifact hashes, exact UUID path, major:minor, PARTUUID,
size, original 4096-byte header digest, scope and unique one-use run_id. Verbal
approval is procedural and is not cryptographic authentication or proof. Keep
the permanent consumed-run record, partition lock and durable active-recovery
marker. The current helper-policy commit must have green non-privileged
GitHub CI before the read-only plan gate.

The fixed /var/lib/swapz/physical-recovery base must be root-owned mode 0700,
beneath root-controlled parents, on persistent physical storage and not on the
selected swap partition. The helper validates storage and identity. Persist and
fsync the original header, recovery state, reviewed artifact snapshots and a
bounded results.json before swapoff or block-zero writes. Results retain the
timestamps, hashes, selected device identity, original swap row, mapper
identity, per-phase return/output and dmsetup/block-stat observations, final
header digest, final swap row, recovery state, and mapper/module/unrelated-map
cleanup status. Never record raw page contents.

After a read-only plan shows every device, source, artifact, recovery, verbal
review and unconsumed-run gate positive, one helper run may execute the bounded
positive correctness sequence: the opened-DM-UUID byte-exact round-trip,
delta64 write/verify, segmented write/verify and ordinary readback,
cross-representation readback, and THP/compound-folio write/verify/readback.
Reverify exact mapper identity before and after each invocation and record
dmsetup status and selected-partition block statistics. A failed phase stops
the suite and immediately enters recovery; never retry it with the same
approval.

The helper must remove only its exact mapper, unload only a positively
same-process-owned module, restore and reread the exact original 4096-byte
header, reactivate only the original partition with its original size and
priority, durably mark recovery COMPLETE and remove the active marker. Preserve
the consumed approval and all recovery/results evidence. Final success also
requires an absent helper mapper, unchanged unrelated mapper inventory,
safe module cleanup, matching original/restored header digest, the same active
swap major:minor/size/priority and no outstanding active marker. Any mismatch,
unexpected state or recovery uncertainty stops the run and requires review.

Excluded from this first physical round: performance/endurance work, synthetic
failure injection, fault ordinals, DISCARD/TRIM, 4096-page rewrites, GC or
resource pressure, timing-dependent suspend/drain and emulated storage-rate
models. Results remain correctness evidence for that one partition/run only.

Critical path:
verified owner report and live hashes -> narrow helper policy plus rootless
regressions -> push policy commit and require green GitHub CI -> verify or
create only the fixed recovery base -> bind a fresh one-use verbal record to
the current helper commit and exact device -> require a fully positive
read-only plan -> one bounded physical run -> exact recovery/restoration proof.

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

### Physical-PC full-capacity and live-swap qualification

The current mission is to qualify the maximum safe logical capacity backed by
the complete `/dev/sda4` partition, then prove actual Linux swap-out/swap-in,
GC/churn, shutdown, recovery, and rollback on this physical PC. The earlier
11/11 physical-backed byte-correctness smoke remains a separate bounded pass;
it did not activate its mapper as system swap and did not qualify live swap.

The source geometry gives an authority admission limit, not yet a verified
production capacity. `/dev/sda4` is 17,179,869,184 bytes. After the one-block SWZ
header and rounding down to 256-block (1 MiB) segments, 4,194,048 physical data
blocks remain. With the current `ceil(logical_pages / 8)` reserve rule, the
largest admitted logical target is 3,727,872 pages: 15,269,363,712 mapper bytes
and 14,911,484 KiB of Linux-usable swap after its first header page. The
authority reserves 465,984 blocks (1,908,678,144 bytes) for GC. Capacity-index
arrays are 132,398,304 bytes (126.26 MiB), excluding fixed caches, scratch,
worker state and allocator overhead. The native boundary regression now passes
through production authority C, including rejection of the next page and
initialization of all capacity-dependent authority arrays. It does not
establish that the loaded target can allocate, reclaim or sustain GC at this
new maximum. The previous loaded maximum-target constructor and boundary probe
ran on exact source `6ff945e8c5e6671f9ffd6d1920343190ae1e5e28`, whose authority
used the older `ceil(logical_pages / 4)` policy and admitted 3,355,136 pages
(13,742,637,056 bytes). That owner `make test` and its report-only publication
`d6c1edca3ea21836e01ad0a8c087bfda4aeaf470` remain valid historical evidence for
that older limit; they do not qualify the new `/8` maximum. No owner `make test`
has yet qualified this capacity-policy change.

On that older source, the loaded maximum-target constructor used an owned
RAM-backed lower sized to the then-usable geometry. Device discovery recorded
667,648 mapper logical READ bytes before the probe's own data phase; their
userspace source was not identified. Constructor lower statistics and physical
READ/WRITE counters remained unchanged. The boundary probe verified byte-exact
writes and reads at logical page 0 and the old final admitted page, using only
two 4 KiB pages of data and revalidating the opened mapper UUID and full table.
Its reported lower deltas were 24,576 READ bytes and 8,192 WRITE bytes, with
zero target failures. This confirms bounded old-limit boundary addressing; it
does not fill the volume or qualify sustained maximum-size writes, worst-case
RAW occupancy, GC or Linux `swapon` behavior. The historical qualified artifact
hashes are formatter
`7f38c6f4226142ceb0c655009f0917d7370ccd0aac7a5db110148b1a861e00e0`, module
`e9001e487e3a86f2404c716f69bb01aa4cc4676f4a5f869201468d1a91850d67`, and
oracle `f47c6f9c9ca97d4d580e0a2d88efcb41cca8d34f4a35e0456a4a4d9a6e85ffe8`.
The probe uses only owned RAM-backed `null_blk` and does not write to the
user's live swap partition.

During this `make test`, a read-only `lsblk` inventory was run during the late
SD read-coalescing matrix. Because `lsblk` may probe a newly created mapper,
late performance samples may include observer I/O; do not use them for a
performance conclusion. The maximum-capacity boundary phase had already passed
before that inventory. At the post-run check, `/dev/sda4` remained ordinary
swap on 8:4 with priority -1 and the original header hash, with no swapz mapper
or module. Usage was 4,316,828 KiB at the immediate post-run check and
3,942,280 KiB in a later read-only snapshot; both were nonzero. At that later
snapshot `MemAvailable` was 8,733,600 kB and memory PSI `full avg10` was 0.97%.
The zero-used live-swap admission gate remains blocked; the pages must remain
under normal Linux swap.

Issue #76's live-swap supervisor now carries the owner's 2026-11-02 decision for
one bounded no-fallback trial: swapz as the sole swap area on `/dev/sda4` at the
maximum admitted capacity (3,727,872 pages, 15,269,363,712 bytes), at most 30
minutes, with RAM below 50 percent before the original swapoff and one bounded
cgroup swap-pressure check inside the window. The owner waived the separate
external-review requirement for this one trial. No reviewer approval exists in
the repository, and the waiver is recorded as an owner decision. Execution is
enabled only for an approval bound to a CI-passing HEAD. Whether the trial
produced real swap-in and swap-out is recorded in its results, not assumed here.
This is not production readiness: persistent boot integration, sustained GC and
churn, and physical power-loss recovery remain unqualified. Loss of the volatile
swapz mapping authority still means pages already stored through that mapping
cannot be reconstructed.

No fallback swap is required by owner decision. A swapfile on root F2FS
(`/dev/sda3`) would share the same USB physical device as `/dev/sda4`, so it
could not protect against loss of that device. Reopen fallback only if the owner
asks for it.

The primary systemd manager is being developed in native userspace C and its
package units remain disabled. `swapzctl primary plan` reports the maximum
capacity arithmetic and strictly parses `/proc/swaps` to report the active
entry count and target size, priority and use. It also performs read-only
by-UUID/by-PARTUUID/device identity, exact-size and original swap-signature
checks when run on the host. The direct-C fixture disables those live reads.
It verifies the original 4096-byte header against the recorded SHA-256 digest.
It checks recovery-directory ownership/mode, an allowlisted persistent
filesystem, direct separation from 8:4, and an absent active marker. Its
read-only sysfs checks separately resolve the recovery and target partitions
to physical parent devices, require direct physical-partition backing, and
reject virtual/stacked sources or nonempty holder lists. It reports that the
recovery directory is on the same physical USB disk as the target, so this
state is persistent across process exit but does not protect against failure
of that whole device. Btrfs remains excluded until multi-device ancestry can
be verified. It also strictly parses mountinfo, confirms `/dev/sda4` is not
mounted, and resolves the root mount to a direct physical partition distinct
from 8:4. It reports separately that the root and recovery filesystems share
the target's physical USB disk. It also inventories `/sys/module/dm_swapz` and
`/sys/block/dm-*`, requiring the module and all SWAPZ-namespaced mappers to be
absent. Exact runtime ownership, swapz target table/capacity, and the lifecycle
remain unchecked, so the plan stays BLOCKED. Provision, activation, teardown
and recovery are disabled.
The installed mapper service now orders before and conflicts with the exact
UUID-generated systemd swap unit for `/dev/sda4`; package installation still
leaves both swapz units disabled and does not alter the host's fstab.
Its condition and uninstall guard now use the same stable
`/var/lib/swapz/physical-recovery/primary-state.json` location as the durable
state-record primitive. No lifecycle command writes or consumes that file yet.
The earlier Python manager draft was removed because production Python is
outside this repository's coding standards. The remaining implementation must
integrate the permanent root-controlled PARTUUID lock primitive with each
lifecycle operation and add durable state transitions, initial provisioning,
checked restoration, startup-failure rollback, exact mapper/module ownership,
and interruption recovery. Lock acquisition and durable one-use owner-claim
primitives now have direct-C regressions. A bounded state-record replacement
primitive now uses file fsync, checked atomic rename and directory fsync, with
rootless symlink/update tests. No primary lifecycle command uses the lock,
owner claim or state replacement yet. No live swap or boot integration has
been qualified through this manager. Do not enable its units until those paths
and the exact-host qualification gates are closed.

The native manager now has strict canonical parsing and formatting for its
small durable lifecycle-stage record, plus a run-ID-aware transition predicate
that preserves original recovery provenance. Its state writer checks the
permanent lock and exact owner claim, rejects illegal transitions, and uses
the durable replace primitive. Owner release requires a matching `COMPLETE`
state, removes only the active marker, and preserves the consumed record.
Rootless coverage exercises these paths, including rejection of a competing
lock and a new run after completion. The record is only a stage envelope, not
the immutable device/artifact/backup recovery manifest. A per-run original
4096-byte header backup now has an exclusive-lock/claim-bound writer, atomic
no-replace installation, fsyncs, SHA-256 verification and a strict reader with
rootless round-trip and tamper-refusal coverage. The immutable manifest now
binds run ID, qualified source commit, userspace and module artifact digests,
qualification-report digest, fixed partition identity, original-header
digest, maximum logical capacity, and exact generated mapper identity and
table. Its parser is canonical and fail-closed; its writer and reader require
the owner claim and lock and enforce durable no-overwrite installation and
verified readback. Rootless regressions cover round-trip, invalid source
digest, fixed-identity tampering, no-overwrite, and output preservation on
failure. These storage and format primitives do not prove that supplied hashes
came from accepted qualification evidence. No privileged lifecycle command
uses these primitives yet; qualification-evidence validation, provisioning,
mapper ownership, startup rollback and recovery remain unimplemented and
unqualified. Fixed-size manifest fields are validated within their declared
buffer bounds before formatting or filename construction.

The next checked-restoration primitive now accepts only a read/write descriptor
for the fixed 8:4 target with exact 16 GiB geometry, compares the complete
current 4096-byte header with an expected value, writes the replacement with
short-write handling, fsyncs, and proves exact readback. Its rootless fixture
uses a temporary regular file and confirms stale-header refusal. The API
is paired with a fixed-path exclusive-open helper that checks `/dev/sda4`, the
UUID link, and PARTUUID link before and after opening the UUID path with
`O_RDWR|O_EXCL`, and checks the opened block descriptor's identity and exact
geometry. Rootless alias tests verify same-target acceptance and substituted
target refusal using temporary files. They do not prove block-device
exclusive-open semantics, physical geometry, or recovery behavior. The
immutable manifest primitive now exists, but qualification-evidence validation
and lifecycle integration are still required before use. Privileged execution
remains disabled.

Header digests now use an in-process SHA-256 implementation instead of
spawning `/usr/bin/sha256sum`; rootless tests cover empty and `abc` vectors, a
known multi-block digest, and overflow refusal with preserved output.
The bounded artifact-FD hasher rejects writable, unsafe-mode, hard-linked,
oversized, or changing regular files and preserves its output on refusal. Its
rootless tests pass, but no primary lifecycle or qualification checker uses it
yet.
