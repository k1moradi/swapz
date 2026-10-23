# Benchmark Standard

**Immutable naming policy (read before every prompt):** The project is `swapz`; the kernel module is `dm-swapz.ko` (loaded as `dm_swapz`); the Device Mapper target is exactly `swapz`; and the module alias is `dm-swapz`. Never put implementation-generation numbers in product, module, target, source-path, report, workflow, helper, or schema names. `SWZ` is the current unversioned on-disk format identity; do not assign a format version until an incompatible format boundary is justified.

**Single official test command (read before every prompt):** Run `make test` at the repository root for every supported swapz test and benchmark. A complete run must report BLOCKED (nonzero) if safe noninteractive privileged qualification cannot run. Do not create, publish, recommend, or document alternative test commands. Private scripts and CI jobs are implementation details, not operator interfaces.

## Objective

Benchmark the one product, `swapz`, against an uncompressed `off` control using the same immutable logical workload. The Device Mapper target is exactly `swapz`; the module alias is `dm-swapz`.

A performance result is useful only when the final logical image is byte-exact and source/fixture/trace provenance matches. The north-star metrics are independent lower READ and WRITE bytes **and** requests for completed useful work, including GC and flush effects, with acceptable useful throughput, read p95/p99, CPU and RAM.

## CPU and host-load context

Codex, editors and other applications compete with the benchmark. Each timed
mixed/write-only arm and each separate READ pass records boundary snapshots
of host CPU ticks and CPU PSI waiting time, plus online/affinity CPU counts.
The console shows host activity, CPU waiting, steal time and replay CPU cores
for the mixed arms; individual write-QD and READ observations remain in the
JSON. Sampling runs outside the throughput stopwatch, without an extra polling
thread. Its boundary span is reported separately, and short or unsupported
observations are explicitly unavailable.

Host activity includes both useful benchmark/kernel work and background work.
CPU PSI indicates that runnable work waited for CPU, without attributing the
delay to an application. Neither metric establishes an idle host. Use the
paired results with these limits; background load can still vary within a
pair. Comparing an earlier idle run with a Codex-active run cannot establish
a code speedup/regression. Native/offline CPU timings have the same background
load caveat. No numerical correction is applied to throughput.

The kernel documents [CPU ticks](https://docs.kernel.org/filesystems/proc.html)
and [PSI waiting totals](https://docs.kernel.org/accounting/psi.html); the
report uses interval deltas, rather than the PSI rolling averages.

## Current synthetic models

### Production delta64 attribution and Core-2 cache baseline

The earlier report `1df2e5a6d7c52682c2ac048310b0ed2f932a2791` tested source
`5bdd040334ee0739e1663e98eef4c875a1c4629a` and passed all five stages
on owned RAM-backed `null_blk`. Production delta64 telemetry is decisive for
this workload: every mixed arm observed 12,301 eligible pages but zero
classifier passes, attempts or adoptions, with zero encoded payload bytes
saved. Delta64 therefore changed neither extent packing nor lower I/O in this
loaded run. The native structured corpus remains separate opportunity evidence:
threshold 24 models 257 -> 205 physical blocks and 182 -> 133 extents.

The same report is the pre-change Core-2 cache baseline. Fast packed reads show
sequential lower READ 2830 KiB / 308.2 requests / 5.54 ms p99 and seeded-random
2493 KiB / 623.2 requests / 5.63 ms p99. Read-engine wall time excluding lower
I/O is 6.0 ms sequential and 9.4 ms random. These are the comparison points for
the subsequent 128-set x four-way metadata directory and block-zero copy-avoidance
round; host-load and lower-I/O caveats still apply.

Successor reports add metadata set lookup/hit/probe/replacement counters and
cached-block payload-copy bytes. A source-level reduction in probes or memcpy
traffic is not itself a performance claim: retain lower bytes/requests, useful
throughput, p99, read-engine attribution and host-load evidence in the verdict.

The Core-2/delta64 packing successor keeps that owner baseline and changes two
measured mechanisms together. Metadata directory tags become 16-byte entries in
aligned 64-byte four-way sets, with epoch invalidation instead of clearing 512
valid bytes on normal mutations. Delta64 keeps threshold 24 for RAW/>2024-byte
rescue, while <=2024-byte LZ4 pages may use threshold 16 only when the engine can
name a lower 4/8/16KiB SWZ packing cliff; adoption on that path requires crossing
the cliff. Production status additionally reports pack eligible/attempt/cliff/
adopted counts and score bands 0-7, 8-15, 16-23 and 24+.

Report `6f5c6e56e6d8` qualified source `9a802eff7d9d` with rescue off.
Its fast random reads use 3592 KiB and 734.6 lower requests, with 71.2%
directory hits and 309.4 replacements. Source inspection confirms that sibling
reads can duplicate a metadata key across ways; this is a defect before any
remaining distinct-key conflict question. Alpha.26 deduplicates commit, drains
late producer work before suspend invariants, and aligns preparation elements.
Report `85aeac4cbb36` then qualified this repair at source `5bf2c0a6f038`.
Keep the mixed read-bypass async gate and classifier policy fixed
for attribution. PACK_READY service-dry counts alone do not establish how many
windows that gate excluded, and a rounded 0.00 run-slot mean is not zero usage.
Consider a separate same-source gate A/B after this repair is qualified.

Alpha.27 is a separate, externally reviewed metadata-cache experiment. Each
key may reside in either of two distinct four-way sets within the same
512-slot store. Primary hits keep a one-line lookup; secondary hits and misses
inspect at most eight tags. Replacement uses an invalid candidate before the
oldest of the two sets, after checking both for an existing key. New primary
and secondary hit counters must sum to total directory hits, and the console
prints their percentages with the common lookup denominator.

The current qualified comparison is fast random 2993 KiB / 678 requests and
about 6.6 ms engine non-I/O wall time. The older 2493 KiB / 623.2-request
result is a historical target, not an acceptance oracle: write placement and
host load differ between reports. Acceptance requires fewer lower READ bytes
and requests with exact data and preserved useful throughput/read tails, while
retaining most of the engine-time advantage and inspecting CPU/PSI context.
Secondary hits alone do not prove saved I/O. This experiment is uncompiled and
untested locally and does not implement Step 3 asynchronous TRIM.

Rootless planner acceptance includes a deliberately one-byte boundary: nine
1803-byte records require five physical 4KiB blocks in five one-block extents under the existing
lower-read tie-break, while nine 1802-byte records fit in one 16KiB extent. The owner run must still demonstrate
whether real windows see that opportunity and whether lower WRITE bytes/requests
fall; cliff crossings alone are not a physical-I/O claim.

### Maintained device settings

Mandatory loaded benchmarking uses newly owned RAM-backed `null_blk` only:

- slow model: 10 MiB/s lower cap, 1 ms completion delay, blk-mq with one
  submit queue and `hw_queue_depth=1`;
- faster model: 80 MiB/s lower cap, 0.15 ms completion delay, blk-mq with one
  submit queue and `hw_queue_depth=64`.

These model latency/bandwidth behavior; they are not measurements of real SD cards or SSDs. Do not label them as physical-media results. The configured mbps value is a lower-device MiB/s cap, not a promise that unmerged 4KiB raw I/O reaches that rate. Reports therefore show the cap converted to decimal MB/s, the analytical 4KiB latency ceiling (4096 * hw_queue_depth / completion_nsec), their minimum, and measured raw sustained-QD32 throughput. On the slow profile the 1ms/depth-1 ceiling is 4.096 MB/s even though the bulk cap is 10 MiB/s. This table is analytical model attribution, not a bulk calibration measurement. Every timed arm samples the positively identified lower device's block-layer READ/WRITE in-flight counters and reports sampled boundary depth, peak and time-weighted mean. swapz mixed arms also report K=1 immutable-run slot occupancy from async submission through ordered publication.

The mixed QD32 matrix keeps four sessions on the slow model as a bounded directional control and uses ten fast-model sessions arranged as five adjacent counterbalanced sync/async matched rounds. It includes identical useful work, independent lower counters, full-image verification and bounded packed-read checks. The fast matched deltas carry two-sided Student-t 95% confidence intervals.

The latest successful standard owner matrix tested source
`174d42eb7135899d4bc0acb22ea82f5be1317f5f`, passed all five stages, and
published report-only commit
`edab5b87344b33f95b2152dab5efbc39fdb0b1a0`. It qualifies that exact
source on owned RAM-backed `null_blk`; current `main` has since advanced and
requires a fresh complete owner run before current HEAD becomes the qualified
baseline.

Five matched fast-model async/sync sustained-write pairs measured QD4 +1.66%
throughput (95% CI [+0.33%,+3.00%]), QD8 +23.88%
([+18.52%,+29.24%]), and QD32 +22.15% ([+15.65%,+28.65%]). QD8 lower
WRITE requests fell 17.96% while bytes rose 0.54%; QD32 requests fell 9.96%
while bytes were statistically neutral. Production lower-WRITE depth remains
fixed at one.

The same source passed the predictor-first positive delta64 A/B and the current
ID63 confirmations. Rescue remains default-off pending representative content;
READ coalescing remains default-on with an eight-block fixed cap. Loaded
lifecycle evidence again exercised GC relocation, whole-segment DISCARD,
packed placement and byte-exact readback. Low-RAM/heavy-CPU, representative
long-run churn, real kernel swap and physical-media qualification remain open.

## Timed boundaries

Exclude fixture generation, device provisioning, worker allocation, buffer setup and warmup from measured logical throughput. Include the measured I/O and required final drain/fsync. For sustained write-only runs, start lower-I/O/kernel snapshots before releasing the persistent workers' measured start gate. Lower-sector/request deltas cover the same interval.

Report replay-process CPU separately from kernel callback wall residency.
Callback wall is not CPU time: ordered callback wall includes synchronous
lower-I/O sleep and callback wall may include scheduler delay. ID24 additionally
reports scheduler-accounted sampled worker CPU from
`current->se.sum_exec_runtime` for ordered and preparation work.
`read_worker_cpu_ns` is retained as a zero-valued compatibility token after
ID39 helper removal. Direct boundary samples can materially miss short callbacks that return before
the scheduler updates the current entity, so treat them only as a lower-bound
diagnostic. The report also carries separate ordered/preparation LZ4 and copy
timers and derives measured non-sleeping phase floors from LZ4/CRC/copy plus
ordered commit-non-I/O work. Those floors still do not equal total worker CPU;
use external scheduler accounting before worker-count/affinity decisions. RAM-backed 4MiB read tests are not cold physical swap-in.

Window-size bins, close reasons, one-page close reasons, deadline contexts,
burst-learning counters, preparation counters and GC-victim attribution are
sampled by `io-replay.py` at this same measured boundary. Full-process
`SWAPZ_STATUS_BEFORE/AFTER` output is not used for those report tables because
it also contains prefill, warmup and post-mixed packed-read population.
`retained_burst_target` is an end-of-interval gauge, not a delta.

The current unqualified candidate also retains successfully read payload blocks
from one immutable 16KiB extent so sequential sibling records do not re-read a
block already present in `read_scratch`. This is a duplicate-I/O elimination
experiment, not yet evidence that the faster packed-read verdict becomes
FASTER. The next owner run must report actual lower READ bytes/requests and
latency before any such claim. It also reports
`batch_snapshot_crc_wall_ns` for the unchanged full-transaction pause/resume
CRC so ID 12 can be judged from measured cost rather than estimated hash bytes.

## Current directional result

On the latest qualified source, fast sequential adjacent-range READ coalescing
reduced lower requests 17.53% (paired 95% CI [-19.71%,-15.35%]) and p99
5.43% ([-9.70%,-1.16%]); useful throughput moved +8.48%
([-2.78%,+19.74%]) and therefore remains statistically unresolved. Fast seeded
random changes in requests, p99 and throughput all overlap zero.

On the serial-depth model, sequential requests fell 20.75%
([-23.32%,-18.19%]), p99 fell 12.24% ([-21.69%,-2.78%]), and useful
throughput rose 16.61% ([+13.78%,+19.43%]). All three intervals exclude zero.
Cap evidence subsequently fixed the production coalesced span at eight blocks;
the runtime cap selector is retired.

Loaded packed placement retained zero internal holes and zero hole-induced run
splits; live GC exercised 20 victims/rotations and verified 4096 pages. The
separate low-RAM/heavy-CPU release gate remains open. Next collect that
resource-pressure evidence and realistic churn/GC/TRIM before deciding on
asynchronous TRIM. Physical media, real swap semantics and endurance remain
unqualified.

## Confirmation gate

Fast and serial ID63 remain five-pair confirmations because they are promoted
request-efficiency mechanisms. The owner run must continue to report paired
95% CIs for useful read throughput, p99, lower bytes and lower requests, with
zero `parallel_read_coalesce_extra_blocks`.

ID64 no longer has a confirmation gate. Its loaded A/B is removed. The active scheduling question is shallow K=1 detachment: fast QD4/QD8/QD32 use five matched sync/async rounds while fast mixed retains five matched pairs.

ID65 and ID66 are owner-qualified at source
`2fabd0dc4b3fe09b8e52e9a624e9452647229e09`. The READ helper remains absent
and compatibility telemetry stays zero. ID63 now carries the entire grouped-slot
execution path: a non-ID63 candidate must return before slot preparation,
cache-LRU scans or cached-block copies. Standalone same-extent grouping is
retired.

Multi-page DISCARD retains all-or-nothing
generation/mapping/shared-extent-liveness validation with no per-physical-block
discard epoch/count arrays. The temporary live-ref accounting must be fully
restored before either error return or commit.

## Deferred idea evidence

**ID38 K>1.** Repeated paired depth-1/depth-2 evidence did not establish a
useful service benefit. Production lower-WRITE depth is fixed at one, the
runtime selector is retired, and the second-slot allocation/append path has
been removed. Ready-wait counters remain passive evidence.

**ID63 adjacent distinct-extent READ coalescing.** The latest qualified source
(`174d42eb7135...`) reconfirms the production mechanism. Fast sequential lower
requests improve 17.53% and p99 5.43%, while the useful-throughput confidence
interval overlaps zero. Serial-depth sequential requests improve 20.75%, p99
12.24%, and throughput 16.61%, with all three intervals excluding zero.
Production keeps `read_coalesce=1` and fixes the maximum coalesced span at
eight blocks; exact-current-main confirmation is pending only because source has
advanced after the qualified report.

Passive evidence finds 162.4/207.0 sequential distinct pairs physically
adjacent but only 2.6/392.2 random. The bounded active experiment is stricter:
prime private slots from the shared caches, derive the exact missing block range
for every grouped BIO, and merge only when both missing ranges are nonempty,
individually contiguous, immediately adjacent, in one 1MiB segment and <=8
blocks total. Issue one lower READ with no padding, seed only private slot
scratch, then run the unchanged per-record metadata/generation/CRC/decompression
path. Shared cache publication still waits for every grouped read and upper copy
to succeed.

All queue depths may use one-request ID63 coalescing on the ordered worker.
Standalone same-extent slot grouping and the rejected helper dispatch are
removed. When coalescing is disabled or the first two immutable extents are not
physically adjacent in one segment, selection must return before slot
prepare/prime/absorb work and leave FIFO ownership untouched.

**IDs58/59.** Current fixture has zero nonzero same-filled writes and extreme
128-payload synthetic duplication. Keep representative-corpus evidence only.

**ID61 foreground GC pressure.** Timed mixed I/O still sees zero victims, so
the existing owned-RAM lifecycle phase is the evidence surface. Its five
capacity-pressure rounds report total successful useful-WRITE wall and one
per-round WRITE p99, while kernel status brackets the same phase for total
foreground-GC wall, victim-choice wall/calls, the existing
no-headroom skip count, logical-map entries scanned, segment-score entries
scanned and relocation-map entries scanned. Round 0 is
the pre-pressure latency baseline; the maximum p99 from later rounds is the
pressure observation. Report GC wall as parts-per-million of useful WRITE wall.
This is synthetic owned-RAM evidence and must not be relabeled physical-device
latency. The owner pressure run put foreground GC near 0.8% of useful-write
wall, refuting a background worker at current geometry. Victim selection now maintains per-segment live-byte/I/O/min-block scores with
the existing exact mapping count, so loaded qualification requires zero
`gc_choose_map_entries`. ID61b relocation is also production-qualified:
report `85aeac4` records 20 relocation-list visits for exactly 20 relocated
pages, zero victim-selection map visits, 1,280 segment-score visits and
byte-exact verification after 20 victim rotations. The portable full-map path
remains only as a compatibility fallback for callers without the sidecar.

**ID62 physical media.** No current benchmark may collect physical evidence.
ID29/ID63 RAM qualification does not authorize physical storage or active swap.

**ID72 logical allocator fairness.** The production switch exists, but the
official loaded harness still pins `logical_open_balance=0`; there is no owner
loaded A/B. The latest qualified baseline already reports segment opens
1/1.25/2 min/mean/max across 64 segments and 80 total opens, which is the
minimum possible integer min/max spread for that workload. A meaningful future
A/B must deliberately create skewed reusable-segment histories and compare
open-count spread, allocator probes/wall time, GC work, lower I/O, useful
throughput and p99. RAM `null_blk` results remain allocator-fairness evidence,
not NAND-wear evidence.

## ID67 predictor evidence and production route

The native ID67 evidence remains the measurement basis for the opt-in
page-local delta64 rescue, but production routing is predictor-first. The
scalar classifier runs before ordinary LZ4. Score >=24 pages try delta64 plus
the rescue LZ4 first; candidates <=2024 bytes may be adopted directly and skip
ordinary LZ4, while larger candidates fall through to the strict ordinary-LZ4
comparison. Lower-score pages run ordinary LZ4 first and may use threshold 16
only when the production planner identifies an exact lower SWZ packing limit
that the candidate crosses. Rescue is default-off.

Earlier loaded enabled-policy evidence observed eligible pages but zero
classifier passes, transform attempts or adoptions, which justified the
default-off policy. The current predictor-first route has since passed a
controlled positive-fixture rescue A/B with 4096 direct adoptions, -27.04%
lower WRITE bytes and +5.15% useful WRITE throughput. That is positive synthetic
evidence rather than representative swap prevalence, so the default remains off.
The following historical/native controls continue to measure routing quality
and backend cost. ID67a.3 uses
`anon-page-fixture.py` SHAKE-generated entropy, mixed and medium pages plus
generated zero/repeated-word controls. The sampled delta64 signpost runs only
after raw LZ4 leaves a page above the rescue threshold and never treats an
unchanged adjacent word (delta zero) as predictor evidence. Positive controls are
generated independently in C and cover pointer arrays, page-table-like entries,
u32/u64 counters/timestamps, slowly varying floats/doubles, two-field structs and
cacheline-local mixed structured/high-entropy records.

The evaluator now keeps only whole-page delta64. Retired comparator
implementations are removed from current source; historical evidence remains in
Git. The selected scalar/SSE2/AVX2/NEON path must match the portable scalar
classifier and transformed bytes before its measurement is accepted. It records
transform/inverse/second-LZ4 time, adopted representations, RAW rescues and
>2024 -> <=2024 crossings. The ID67a.3 delta64 signpost samples 8 page-wide
pairs first and returns immediately below score 2; passing pages extend to 32
evenly strided pairs. Its ns/page is measured by 256 repeated batched eligible
page sweeps, amortizing timer overhead. Thresholds 4/8/16/24/32 retain
per-profile false-call reporting.
Baseline, ungated candidate, and each classifier-routed threshold length
sequence are fed through the production `swapz_engine_plan_bounded()`; routed
physical 4KiB blocks/extents saved are the promotion metric. Compression ratio
or ungated transform savings alone is not promotion evidence.

The native output remains explicitly labeled
`OFFLINE_NATIVE_ONLY_NOT_KERNEL_POLICY` and is sanitized into the official
report because its timings are not loaded-kernel performance. Production policy
is qualified separately by the loaded matrix and byte-exact lifecycle tests.

Historical multi-model runs are retained only as decision evidence: delta64 was
the winner and the alternatives are no longer maintained. ID67a.2 fixed the
delta-zero classifier bug; the owner run's threshold 32 produced
0/141 negative calls and 256/320 useful structured calls, while ungated delta64
saved 65 planner blocks. Its 385 ns/page single-page timer result is not a
promotion-quality cost measurement. Initial ID67a.3 rootless native CI measures
61 ns/eligible page across 118,016 batched calls. Threshold 16 is the first
tested zero-false-call point and retains 52 of 65 ungated planner blocks saved
plus 49 extents; thresholds 24/32 produce the same routed geometry. This is
promising offline evidence, not owner-loaded or production evidence, and it
still misses the provisional <60 ns/page target by 1 ns. The fixed 24-pair second stage is unrolled without changing sample positions.
ID67a.4 introduced explicit SIMD with isolated kernel-FPU translation units and
static-call dispatch. Current x86 production supports SSE2, AVX2 and AVX-512
full-page transform/inverse backends; arm64 supports kernel-mode NEON, with
portable C fallback. The owner SSE2 evidence showed the sparse classifier
regresses under vector packing, so the classifier remains scalar-only.
Transform and inverse remain separate static calls, but current x86 production
dispatch selects the same qualified ISA tier for both: AVX-512 when AVX-512F
and the required xstate are available, otherwise AVX2, otherwise SSE2, with
scalar fallback. arm64 selects kernel-mode NEON when available. Qualification reports routed CPU ns/page and ns/saved-block. Native timing still excludes kernel_fpu_begin/end overhead, so loaded results
remain authoritative for end-to-end cost. SWZ now carries one explicit
per-record delta64 encoding bit without enlarging the 16-byte record.

## Physical media

No current benchmark authorizes physical storage or active swap. A future
real-device study requires separate owner authorization, exact device ownership
and alias checks, backup/data-loss acceptance, independent safety review and a
pinned source/procedure. RAM `null_blk` evidence must never be relabeled as
physical-media evidence.

## Settled experiment memory

The ROADMAP optimization evidence table is the canonical anti-retest index.
This benchmark standard intentionally does not retain the chronological chain
of every qualified successor. Git history and report commits preserve those
details.

The following benchmark-specific conclusions are worth keeping here because
they affect how new measurements are designed:

| Topic | Settled conclusion | Reopen only when |
|---|---|---|
| Retained-window grace/recheck timers | Do not wait for future arrivals. Work only with already accepted BIOs and the ordinary bounded deadline. | A new workload shows current finite-accepted policy is the measured bottleneck and can be isolated without changing lower-byte geometry. |
| Deferred singleton age cutoff (ID53) | Rejected and reverted; keep the ordinary deadline. | New evidence invalidates the feedback/artifact mechanism recorded under ID53. |
| Completion-aware zero-tail preservation (ID57) | Rejected and reverted; it contaminated later closed-loop waves. | A new state model can prove wave ownership without stale service evidence. |
| CPU-local/bound preparation | Rejected: better overlap did not improve useful service. Keep unbound scheduling. | Trustworthy CPU attribution plus a new workload shows placement, not queue/service geometry, is limiting. |
| Multiple preparation lanes | Fixed at one producer lane; K=2/K=4 routine A/Bs are retired. | A new workload shows a sustained preparation backlog and a concrete service opportunity. |
| Lower-WRITE depth >1 | Rejected for the current product; second-slot path is removed. | A materially different device/workload proves ready-run pressure and justifies a new ownership design. |
| Direct single-bvec compression input | Qualified; keep direct input with safe fallback. | Only if ownership/page-mapping assumptions change. |
| Final payload CRC removal | Rejected; it is an integrity boundary, not optional benchmark overhead. | Only with an equivalent fail-closed integrity design. |
| Ordinary LZ4 acceleration | Fixed at 1; runtime selector and loaded promotion A/B are retired. | A materially different codec/library/CPU changes end-to-end service economics. |
| Delta64 rescue | Predictor-first route is qualified on controlled positive content but remains default-off. | Representative swap content demonstrates prevalence and matched end-to-end benefit. |
| Adjacent READ coalescing | Keep default-on, exact 2..8 ranges, zero padding, fixed eight-block cap. | New device/workload evidence shows a service regression or a larger cap has a measurable opportunity. |
| Same-extent standalone READ grouping | Rejected/retired; shared caches remain. | A new cache/layout regime creates a measured request opportunity not covered by ID63. |

Do not repeat a settled A/B merely because the detailed narrative was removed
from this file. Reopen it only under the condition above or the corresponding
ROADMAP row.

## Current qualification protocol

Current benchmark work must preserve these contracts:

- **Ordinary LZ4:** production acceleration is fixed at one. The native
  1/2/3/4 sweep remains only a byte-exact codec/geometry regression check.
- **Delta64:** rescue is default-off. When enabled, the scalar classifier runs
  before ordinary LZ4; high-score pages may directly adopt a sufficiently small
  delta64+LZ4 result. Scalar and every compiled SIMD backend must remain
  byte-identical, and loaded wrapper-inclusive timing remains authoritative.
- **Preparation:** async preparation owns one unbound producer lane regardless
  of delta64 policy. Predictor scratch allocation may remain rescue-dependent;
  lane count is not.
- **READ coalescing:** merge-off/on confirmation uses the same independent READ
  fan-out in both arms. A merge may combine 2..8 exact contiguous missing
  ranges in one segment, at most eight 4KiB blocks, with zero padding. A
  successful N-extent chain saves N-1 lower requests.
- **Validated cache fast paths:** sequence, generation, logical identity and CRC
  boundaries remain mandatory. Provisional coalesced bytes cannot become shared
  residency before successful validation and upper completion.
- **Publication:** planner/preflight optimizations may reduce CPU work, but no
  fallible check moves after global mutation and final payload CRC remains
  mandatory.
- **Evidence:** compare byte-exact useful work, independent lower bytes and
  requests, useful throughput, p99, CPU/PSI context and the relevant bounded
  internal counters. Internal counters alone never establish a product win.

### Current evidence cycle

Delta64 rescue remains default-off despite the qualified positive-fixture A/B;
representative swap content is the remaining promotion gate. Production
ordinary LZ4 is fixed at acceleration one, delta64 preparation at one producer
lane, lower-WRITE submission at one immutable slot, and ID63 coalescing at an
eight-block cap. The depth-two path and the settled runtime selectors are
retired from current source.
