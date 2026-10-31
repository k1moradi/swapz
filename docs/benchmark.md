# Benchmark Standard

**Immutable naming policy (read before every prompt):** The project is `swapz`; the kernel module is `dm-swapz.ko` (loaded as `dm_swapz`); the Device Mapper target is exactly `swapz`; and the module alias is `dm-swapz`. Never put implementation-generation numbers in product, module, target, source-path, report, workflow, helper, or schema names. `SWZ` is the current unversioned on-disk format identity; do not assign a format version until an incompatible format boundary is justified.

**Single official test command (read before every prompt):** Run `make test` at the repository root for every supported swapz test and benchmark. A complete run must report BLOCKED (nonzero) if safe noninteractive privileged qualification cannot run. Do not create, publish, recommend, or document alternative test commands; the sole owner-approved exception is the development decision loop `make fast_test`, which never qualifies a source, never writes or publishes `test_results.json` and never replaces `make test`. Private scripts and CI jobs are implementation details, not operator interfaces.

## Objective

Benchmark the one product, `swapz`, against an uncompressed `off` control using the same immutable logical workload. The Device Mapper target is exactly `swapz`; the module alias is `dm-swapz`.

A performance result is useful only when the final logical image is byte-exact and source/fixture/trace provenance matches. The north-star metrics are independent lower READ and WRITE bytes **and** requests for completed useful work, including GC and flush effects, with acceptable useful throughput, read p95/p99, CPU and RAM.

Console interpretations must answer the product question before discussing an
internal mechanism. For loaded results, compare swapz with the raw/off control
on useful throughput, latency and lower-device work. Call out a directional
project win only when the observed direction serves the product vision: more
useful I/O and/or lower latency, or less lower-device traffic. Lower WRITE
bytes/requests are the host-I/O endurance proxy; lower READ traffic primarily
supports swap-in efficiency. Neither is direct NAND lifetime evidence. If
benefits and regressions coexist, label the result a trade-off rather than a
win. Internal
sync/async or feature off/on comparisons explain mechanism; they do not turn a
result that still trails raw into a product-level performance win. Mean-value
interpretations are directional only; matched confidence intervals remain the
qualification evidence.

Every stdout table must finish with three compact explanatory layers: a column
legend, an interpretation of the observed values, and a **Project reasoning**
chain in the explicit form **Evidence -> Goal implication -> Verdict**. The last
line must say whether the table is aligned, a trade-off, not aligned,
inconclusive, supporting-only, diagnostic-only, model context, or a claim
boundary. Mechanism/native/model tables must state that they cannot independently
qualify a production optimization. Logical segment-open spread is allocator
fairness evidence only; it must never be presented as NAND P/E or physical wear
leveling.

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

Fresh owned RAM-backed null_blk is sparse: writes to new physical addresses
can allocate host RAM, whereas rewriting an already populated address need not.
Keep backing preconditioning in the protocol identity and apply it symmetrically
to raw and swapz. ID36 already uses full backing population for its separate
memory-pressure gate. ID139 did not establish a material benefit from extending
that protocol to ordinary performance comparisons; do not present prewarming
as a kernel optimization or drop the allocation cost from only one arm.

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

These model latency/bandwidth behavior; they are not measurements of real SD cards or SSDs. Do not label them as physical-media results. The configured mbps value is a lower-device MiB/s cap, not a promise that unmerged 4KiB raw I/O reaches that rate. Historical qualification reports preserve the analytical 4KiB latency ceiling from the configured hardware depth. New directional storage-envelope diagnostics use the aggregate queue capacity
`submit_queues * hw_queue_depth` and then cap it at the workload's offered QD,
because a QD32 replay cannot consume more than 32 outstanding slots. On the slow profile the 1ms/depth-1 ceiling is 4.096 MB/s even though the bulk cap is 10 MiB/s. These calculations are model attribution, not bulk calibration measurements. Every timed arm samples the positively identified lower device's block-layer READ/WRITE in-flight counters and reports sampled boundary depth, peak and time-weighted mean. swapz mixed arms also report K=1 immutable-run slot occupancy from async submission through ordered publication.

The mixed QD32 matrix keeps four sessions on the slow model as a bounded directional control and uses ten fast-model sessions arranged as five adjacent counterbalanced sync/async matched rounds. It includes identical useful work, independent lower counters, full-image verification and bounded packed-read checks. The fast matched deltas carry two-sided Student-t 95% confidence intervals.

`make test` also runs a **directional storage-service envelope sweep** to expose bottlenecks that an 80 MiB/s cap can hide. These remain RAM-backed `null_blk` models and must never be described as measurements of a specific SD card or SSD:

- modern-SD envelope: 100 MiB/s, 0.5 ms completion, one submit queue, hwq 4;
- SATA-SSD envelope: 500 MiB/s, 0.1 ms completion, one submit queue, hwq 32;
- Gen4-NVMe envelope: 6500 MiB/s, 25 us completion, four submit queues, hwq 64;
- Gen5-NVMe envelope: 12000 MiB/s, 14 us completion, four submit queues, hwq 64.

Each envelope replays the same QD32 mixed workload with production asynchronous preparation and separately replays the positive delta64 write-only fixture. The four modern envelopes use the internal native-C replay helper for both arms so Python Future/GIL scheduling cannot be the dominant timed submitter. Python still owns device safety, immutable-plan validation, provenance, boundary snapshots and the final byte-exact oracle; the helper only inherits the already-open validated target/fixture descriptors and executes the timed I/O. The historical 10/80 MiB/s matrix continues to use the prior Python replay for baseline continuity.

The report compares raw/off with swapz using lower-WRITE byte speedup, lower-WRITE request speedup and useful-WRITE speedup. It additionally reports
`(useful_speedup - 1) / (lower_byte_speedup - 1)` as **bandwidth-opportunity capture** when lower bytes improve. This is diagnostic attribution, not a qualification score: a low or negative value means saved lower-device work is not reaching useful service.

For bottleneck attribution, the same rows expose sampled lower-WRITE peak/mean
depth plus timed swapz fractions for K=1 ready-window wait, ordered-worker
preparation handoff wait, lower-WRITE slot occupancy,
`pipeline_post_lower_wall_ns` (lower callback through ordered
publication/release), commit non-I/O, planner, pack, publication and final
publication CRC. A nonzero K=1 ready-wait fraction is direct evidence that a ready immutable
window was blocked behind the sole lower-WRITE slot. A material post-lower
fraction shows that the slot remained occupied after device completion while
the ordered owner was scheduled and/or publishing. Preparation wait instead
identifies producer/ordered-worker starvation. Modern fast-media rows must also
compare wall time against worker-empty retained deadline closes. A 2 ms
retention deadline is orders of magnitude above a 14--25 us modeled NVMe
completion and can dominate wall time even when lower-I/O request reduction is
excellent. Current Gen4/Gen5 mixed evidence records 197/176 worker-empty
deadline closes with zero K=1 ready waits; count*2 ms proves at least 394/352 ms
of aggregate open-window age reached the deadline, but that age can include CPU
and I/O and is not a pure-idle measurement. Add exact retained idle-wait
attribution before changing the deadline. If ready-wait is small but retention wait dominates, shorten or
eliminate fast-media waiting before widening lower-I/O depth; if post-lower or
commit non-I/O dominates instead, investigate serialized authority/publication.

The latest successful standard owner matrix tested source
`0155a09a0f2ef97daff68da045f615a04000ed02`, passed all five stages, and
published report-only commit
`dc78c9bbffbd2e8178fea9df2ca66006855c22e5`. It qualifies that exact source
on owned RAM-backed `null_blk`, including the ID36 resource-pressure gate and
retained suspend/drain lifecycle.

Five matched fast-model async/sync sustained-write pairs now measure QD4 +3.94%
throughput (95% CI -14.42..+22.30), QD8 +0.95% (-0.98..+2.87), and QD32 +0.94%
(-4.72..+6.61). All intervals overlap zero: the significant ID80 QD8 regression
is gone, but the earlier ID77 deep-QD async advantage is not recovered.
Production lower-WRITE depth remains fixed at one.

The same source passes the predictor-first positive delta64 A/B and current ID63
confirmations. Delta64 rescue is now default-on by owner decision, still
pending representative content; READ coalescing remains fixed-on with an eight-block cap. Loaded
lifecycle evidence exercises GC relocation, whole-segment DISCARD, packed
placement, low-RAM/heavy-CPU pressure and byte-exact readback. Representative
long-run churn, actual kernel swap and physical-media qualification remain open.

## Timed boundaries

Exclude fixture generation, device provisioning, worker allocation, buffer setup and warmup from measured logical throughput. Include the measured I/O and required final drain/fsync. For sustained write-only runs, start lower-I/O/kernel snapshots before releasing the persistent workers' measured start gate. Lower-sector/request deltas cover the same interval.

For the modern-envelope native engine, pre-create all QD worker threads and complete warmup before the READY/GO gate. The parent captures lower/kernel/host boundaries before GO; the helper times from immediately before releasing that gate through the required final `fsync`. Native helper startup, trace staging and latency-result serialization are excluded. Mixed traces retain one barrier per immutable QD wave; write-only traces retain persistent disjoint ordered lanes with no per-I/O Future submission. Timed READs remain byte-verified before their lane can advance.

ID36's pressure-only Python packed-read verifier likewise uses one persistent
job per QD32 lane with reusable barriers and result slots for read-set
population, sequential verification and seeded-random verification. This is a
qualification-harness allocation bound, not a new performance replay engine:
the ordinary 10/80 MiB/s benchmark path retains its historical per-wave
submission for comparability. The ID36 timeout and memory/CPU pressure settings
remain unchanged.

Report replay-process CPU separately from kernel callback wall residency. For native-envelope rows this is the helper process CPU rather than the Python orchestrator;
Callback wall is not CPU time: ordered callback wall includes synchronous
lower-I/O sleep and callback wall may include scheduler delay. ID24 additionally
reports scheduler-accounted sampled worker CPU from
`current->se.sum_exec_runtime` for ordered and preparation work.
`read_worker_cpu_ns` is retained as a zero-valued compatibility token after
the ID39 helper-workqueue removal. Current independent lower-READ fan-out does
not restore a read worker: the ordered worker submits and joins private lower
ranges and retains decode/publication/completion ownership. Direct boundary
samples can materially miss short callbacks that return before
the scheduler updates the current entity. An update inside a callback can
also charge execution from before entry, so these diagnostics are not guaranteed
CPU bounds. The report carries separate ordered/preparation LZ4 and copy timers
and sums partial phase wall time from LZ4/CRC/copy plus ordered commit-non-I/O
work. Those phases can include preemption and do not establish total worker CPU;
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
and compatibility read-worker telemetry stays zero. ID63 owns adjacent-range
coalescing, while the ordered worker separately has bounded independent
lower-READ fan-out through the same private-slot infrastructure. Standalone
same-extent grouping is retired. The final fan-out decision at `11fbc839...`
established large useful-service and tail-latency gains with ID63 disabled, so
fan-out is now fixed on and its runtime selector/routine A/B are retired.

Multi-page DISCARD retains all-or-nothing
generation/mapping/shared-extent-liveness validation with no per-physical-block
discard epoch/count arrays. The temporary live-ref accounting must be fully
restored before either error return or commit.

## Deferred idea evidence

**ID38 K>1.** Repeated paired depth-1/depth-2 evidence did not establish a
useful service benefit. Production lower-WRITE depth is fixed at one, the
runtime selector is retired, and the second-slot allocation/append path has
been removed. Ready-wait counters remain passive evidence.

**ID63 adjacent distinct-extent READ coalescing.** Current qualified source
`0155a09a0f2e` reconfirms the production mechanism. Fast sequential lower
requests improve 11.29% (95% CI -14.35..-8.24), while throughput and p99
intervals overlap zero. Serial-depth sequential requests improve 25.89%, p99
13.69%, and throughput 30.58%, with all three intervals favorable. Production
keeps the fixed-on mechanism and maximum coalesced span at eight blocks.

Passive evidence finds 162.4/207.0 sequential distinct pairs physically
adjacent but only 2.6/392.2 random. The bounded active experiment is stricter:
prime private slots from the shared caches, derive the exact missing block range
for every grouped BIO, and merge only when both missing ranges are nonempty,
individually contiguous, immediately adjacent, in one 1MiB segment and <=8
blocks total. Issue one lower READ with no padding, seed only private slot
scratch, then run the unchanged per-record metadata/generation/CRC/decompression
path. Each constituent may publish verified cache residency and complete only
after its own validation/decode/upper copy succeeds; a later constituent failure
fails still-owned BIOs and the target without retroactively invalidating an
already verified constituent.

All queue depths may use one-request ID63 coalescing on the ordered worker.
Standalone same-extent slot grouping and the rejected helper workqueue remain
removed. The ID63 selector itself must return before coalescing-specific slot
prime/ownership work when coalescing is disabled or no exact adjacent chain
exists. After that rejection, the fixed-on ordered-worker fan-out path may still
prepare private slots for two or more independent missing lower ranges; it
never merges those ranges and preserves same-page ordering across any skipped
retained WRITEs.

**ID79 read-cache/write-window coupling.** Current source preserves validated
metadata residency across disjoint planned one-record writes and reduces fast
mixed lower READ requests to 9.0 in both sync and async. Against qualified
pre-ID79 `ab885372`, the fast synchronous metadata-set hit rate rises
42.94% -> 99.78%, but windows rise 694.8 -> 1793.8 and lower WRITE requests
724.6 -> 1818.2. The production kernel trees match outside `engine.c`, and
the fast fixture/trace/session order are identical; cross-report throughput is
still load-sensitive. Run one temporary source-only ID79-off A/B before changing
retention policy. Do not retain an invalidation selector or deliberately restore
lower-READ stalls as a batching mechanism.

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

**ID72 logical allocator fairness.** The terminal loaded A/B experiment was
executed following the pass of ID36. Using the predeclared five-pair 70%-occupancy
40,960-rewrite cold/hot workload on owned RAM, baseline circular allocation
yielded min 0, max 4, sum 172 across 64 segments (spread=4). Least-opened scanning
achieved identical min 0, max 4, sum 172 (0.00% spread reduction) while regressing
write p99 latency by +9.93% (+18.0 us). Per the terminal decision protocol,
the redundant switch was removed and circular allocator fairness retained as the
sole canonical policy. Logical opens remain allocator fairness telemetry, not
NAND-wear evidence.

## ID67 predictor evidence and production route

The native ID67 evidence remains the measurement basis for the default-on
page-local delta64 rescue, but production routing is predictor-first. The
scalar classifier runs before ordinary LZ4. Score >=24 pages try delta64 plus
the rescue LZ4 first; candidates <=2024 bytes may be adopted directly and skip
ordinary LZ4, while larger candidates fall through to the strict ordinary-LZ4
comparison. Lower-score pages run ordinary LZ4 first and may use threshold 16
only when the production planner identifies an exact lower SWZ packing limit
that the candidate crosses. Rescue is default-on; `delta64_rescue=0` disables it.
Current rescue writes DELTA64_SHUF8 (delta64, eight byte planes, LZ4), while
the historical ID67 timings below measured plain delta64. ID117 records the
shuffle evidence and pending full-matrix/x86 execution gates.

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
Git. The selected scalar/SSE2/AVX2/AVX512/NEON path must match the portable scalar
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
| Retained-window deadline duration | ID83 owner report `64f6e8e1890e` on source `e17f05a1c256` qualifies one bounded fast-tail exception inside the ordinary 2 ms hard deadline: 99.9% of sync and 100% of async fast reached-four observations land by the <=500us bin, while 250us would cut about 2% of them. Cache-hit independent READs dominate the observed wave pivots. The candidate therefore advances the existing hrtimer to sample+500us only for a staged suppressed two/three-record tail and may close sooner on an independent READ pivot. | Reopen the 500us bound only if an exact-source owner run shows material fast mixed regression, lost QD4/QD8/QD32 geometry, or a shifted reach-four distribution; do not generalize it to singletons or arbitrary admission waits. |
| Admission queue + prepared reservoir + opportunistic compressed/RAW dispatch | Admission should be descriptor-only where ownership permits; prepared payloads live in a bounded preallocated reservoir and the ordered dispatcher never waits solely for compression. Existing mixed runs already support compressed extents followed by RAW 4KiB extents. | Queue/reservoir occupancy proves useful run-ahead work and accepted work exists while lower WRITE is idle; a same-source candidate reduces that idle wall and improves useful service without unacceptable slow-media/lower-I/O regression. |
| Deferred singleton age cutoff (ID53) | Rejected and reverted; keep the ordinary deadline. | New evidence invalidates the feedback/artifact mechanism recorded under ID53. |
| Completion-aware zero-tail preservation (ID57) | Rejected and reverted; it contaminated later closed-loop waves. | A new state model can prove wave ownership without stale service evidence. |
| CPU-local/bound preparation | Rejected: better overlap did not improve useful service. Keep unbound scheduling. | Trustworthy CPU attribution plus a new workload shows placement, not queue/service geometry, is limiting. |
| Multiple preparation lanes | Fixed at one producer lane; K=2/K=4 routine A/Bs are retired. | A new workload shows a sustained preparation backlog and a concrete service opportunity. |
| Lower-WRITE depth >1 | Rejected for the current product; second-slot path is removed. | A materially different device/workload proves ready-run pressure and justifies a new ownership design. |
| Direct single-bvec compression input | Qualified; keep direct input with safe fallback. | Only if ownership/page-mapping assumptions change. |
| Final payload CRC removal | Rejected; it is an integrity boundary, not optional benchmark overhead. | Only with an equivalent fail-closed integrity design. |
| Ordinary LZ4 acceleration | Fixed at 1; runtime selector and loaded promotion A/B are retired. | A materially different codec/library/CPU changes end-to-end service economics. |
| Delta64 rescue | Default-on by owner decision; predictor-first route is qualified on controlled positive content. | Representative swap content or the default-on mixed matrix shows no prevalence, or a service/CPU regression versus `delta64_rescue=0`. |
| Adjacent READ coalescing | Keep default-on, exact 2..8 ranges, zero padding, fixed eight-block cap. | New device/workload evidence shows a service regression or a larger cap has a measurable opportunity. |
| Same-extent standalone READ grouping | Rejected/retired; shared caches remain. | A new cache/layout regime creates a measured request opportunity not covered by ID63. |

Do not repeat a settled A/B merely because the detailed narrative was removed
from this file. Reopen it only under the condition above or the corresponding
ROADMAP row.

## Current qualification protocol

Current benchmark work must preserve these contracts:

- **Ordinary LZ4:** production acceleration is fixed at one. The native
  1/2/3/4 sweep remains only a byte-exact codec/geometry regression check.
- **Delta64:** rescue is default-on (`delta64_rescue=0` disables it). The
  scalar classifier runs before ordinary LZ4; high-score pages may directly adopt a sufficiently small
  delta64+shuffle8+LZ4 result. Scalar and every compiled SIMD backend must remain
  byte-identical, and loaded wrapper-inclusive timing remains authoritative.
  In console tables, a timing column that measures only compression of an
  already transformed page is labeled `LZ4 ns`; use a combined delta64+LZ4
  label only when the measurement actually includes both operations. Do not use
  ordinal labels such as “LZ4-2”.
- **Preparation:** async preparation owns one unbound producer lane regardless
  of delta64 policy. Predictor scratch allocation may remain rescue-dependent;
  lane count is not. For an ID83 work-conserving candidate, preparation is
  speculative: report whether each dispatched page was compressed-ready,
  ordinary incompressible RAW, or RAW-selected because preparation was not
  ready. The ordered owner must not wait solely for optional preparation when
  accepted backlog exists and lower WRITE service would otherwise be idle.
- **Work-conserving lower service:** report exact accepted-work/no-lower-WRITE
  idle nanoseconds, idle episodes, lower-WRITE active fraction, ready-run wait,
  RAW-not-ready fallbacks and discarded late-preparation results. A candidate
  succeeds by converting idle wall into useful service, not by maximizing
  compression ratio. Same-source slow/SD rows must retain their established
  benefit; fast rows may spend additional lower bytes/requests only when useful
  throughput or p99 materially improves.
- **Independent READ fan-out:** fixed-on production infrastructure. The final
  five-pair fast-model decision at `11fbc839...` established repeatable mixed
  throughput/tail-latency and packed sequential/random READ gains with ID63
  disabled. The runtime selector and routine A/B are retired; preserve its
  bounded private-slot ownership and same-page ordering contracts.
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
  The official `make test` sustained matrix keeps five matched fast QD4/QD8/
  QD32 pairs and five matched serial QD32 pairs. Generic scheduling changes do
  not alter the codec matrix: x86_64 qualification compiles SSE2, AVX2 and
  AVX-512 objects and arm64 compiles NEON, with byte-exact scalar fallback and
  runtime ISA selection preserved.

### Current evidence cycle

The ID73 scalar hot-path follow-up uses source `9202ce7` as its pre-change
comparison point. It is expected to reduce planner, publication and read-engine
non-I/O CPU work without changing logical work or lower-I/O geometry. Promotion
requires an exact-source `make test`: compare useful throughput/read p99 and
independent lower bytes/requests first, then use planner wall, publication
non-I/O/CRC split, read-engine non-I/O, host CPU/PSI and GC attribution to
explain any change. A lower internal phase timer alone is supporting evidence,
not a product win; unchanged lower-I/O counters are expected for this
semantics-preserving increment.

The structural ID73 follow-up uses `329a10c` as its immediate comparison
point. The native authority-throughput evidence includes two same-host
micro-pairs: full 64-record validation versus metadata-CRC-only validation, and
checked 64-record append versus the caller-proven-unique append used by the
batched engine. Report both absolute ns/call or ns/extent and their relative
difference, but label them supporting CPU evidence only. The owner loaded
matrix remains decisive: geometry/lower bytes and requests must stay invariant,
while `engine_pack_wall_ns` and
`engine_publish_wall_ns - engine_publish_crc_wall_ns` are the primary
attribution metrics for the expected gain.


Report `98db4b028f41` qualifies exact source `b389204` on ARM64/NEON and
splits the ID78 evidence. The completion-state repair succeeds in fast mixed
I/O: async post-PACK sampling rises from 131.4/660.2 PACK_READY closes on the
qualified `8a6dd2a` baseline to 617.4/617.4, async-minus-sync lower-WRITE
requests improve from +31.6 (CI crossing zero) to -12.6 with a 95% CI of
-23.6..-1.6, and async useful WRITE reaches 60.43 MB/s (-3.9% versus raw,
+0.7% versus sync). Preserve the in-flight quiescent guard and completion-aware
bounded `batch_count + local + incoming` sample.

The same run refutes the bundled four-record 16KiB first-pack rule. With
`SWAPZ_MAX_COMPRESSED`, any four non-RAW compressed records fit the existing
4-block class, so the rule is not selective geometry: it makes first-pack state
true at the learned floor of four and closes below the `count > 4U` asynchronous
detach threshold. Fast write-only QD8 async/sync falls from +74.6% on
`8a6dd2a` to +2.2% (95% CI -3.1..+7.5) and QD32 from +14.9% to +0.7%
(-0.2..+1.5). D64-on modern-envelope useful service also falls to 2.86x on
modern-SD, 0.21x on SATA, 0.08x on Gen4 and 0.06x on Gen5 despite approximately
50% lower WRITE bytes. The four-record first-pack branch is therefore removed;
the existing 4-block extent class itself remains unchanged.

Qualification of the split is product-facing. It must keep `b389204`'s fast
mixed tail conservation, significant async lower-request reduction, useful
WRITE/READ service and p99 direction while restoring the deep-QD behavior lost
by the four-record rule. Use `8a6dd2a` as the QD8/QD32 reference (+74.6% and
+14.9% async/sync) and `b389204` as the completion-state reference. Slow/SD
wins and lower-byte/request savings must remain intact, and every modern
envelope must be judged against its same-run raw control. The ordinary
retention deadline, K=1 lower-WRITE slot, one preparation lane, ID63 policy and
SWZ 1/2/4 extent classes remain fixed.

The subsequent owner run on source `443c1e2` is partial because ID36 later
timed out, but its already-completed sustained-QD rows falsify the narrower
four-record-only diagnosis. Fast QD8 still reports learned target 22, 317.6
3-4-record windows, 47.8 deadline closes and async/sync -1.2% (95% CI
-4.9..+2.6); serial QD8 reaches target 37. This established that the completion
boundary, rather than the removed four-record shortcut alone, required further
evidence.

Report `c32e46b6f472` then fully qualifies exact ARM64/NEON source
`c07edd913972` for correctness and resource pressure, but refutes the
staged-only pending split as a performance repair. Fast write-only QD8
async/sync is -8.1% (95% CI -18.1..+1.9) and QD32 is -16.3%
(-18.6..-14.0); their deadline closes rise to 58.8 and 67.8. Fast mixed async
falls to 53.56 MB/s (-14.8% versus raw, -6.8% versus sync), with the
async-minus-sync throughput CI still crossing zero. The internal staged-tail
counters moved in the intended direction, but the product-facing service did
not, so the staged-only sample lockout is not retained as a qualified
optimization.

The next ID78 candidate keeps the completion-only K=1 guard but treats a
PACK_READY completion as one completed closed-loop generation: its count
replaces, rather than accumulates with, older PACK_READY generations whose
upper BIOs have already been released. After finalization the bounded
`batch_count + local + incoming` sample is consumed exactly once. Only the
pre-completion `batch_count` prefix may raise the learned burst target; queued
followers make the finite tail explicit but are excluded from burst learning
because they may already include resubmissions from the just-completed writers.
Staged-only work installs no immediate tail-close target. This
removes the c07 pending-sample lockout without restoring premature staged-only
self-closure. The same candidate evaluates early pack readiness over valid
compressed records even when earlier RAW records share the bulk batch, matching
the existing compressed-before-RAW flush order. Total batch count four remains
a negative first-pack guard, so RAW skipping cannot recreate the refuted
below-detach close. It does not change SWZ, the ordinary deadline, K=1,
preparation-lane count, ID63, or the 1/2/4-block extent classes.

Qualification remains product-facing. On an ARM64/NEON owner run, compare fast
mixed against `b389204` and the c07 regression control, and compare QD8/QD32
against `8a6dd2a`. A lower learned target or fewer deadlines is only
attribution; promotion requires useful WRITE/READ, lower bytes/requests and p99
to remain aligned. The same public `make test` must retain its existing
SSE2/AVX2/AVX512 and NEON backend qualification on the architecture that
supports each ISA.

Configured modern-storage caps remain service-model inputs, not proof that the
host attained that media class. Compare each swapz row to its same-run raw
control and report attained raw throughput/queue depth. A host whose RAM/CPU
cannot drive a configured Gen4/Gen5 cap may still provide low-latency/deep-queue
stress evidence, but not a physical Gen4/Gen5 throughput claim.

The prepared-buffer copy-elision idea remains a separate ownership experiment.
Do not keep producer slots live across a packed lower WRITE merely to avoid the
`prepared_page -> batch_bytes` copy without first proving bounded producer
capacity, suspend/drain safety, immutable lower-run lifetime and no completion
ownership cycle. Final publication payload CRC remains a settled integrity
boundary and is not part of that experiment.

Delta64 rescue is default-on by owner decision after the qualified
positive-fixture A/B; representative swap content remains the evidence that
keeps or reverts it. Standard sessions run the default, while the paired A/B
off arm and the medium-mixed envelope control pin `--no-delta64-rescue`. Production
ordinary LZ4 is fixed at acceleration one, delta64 preparation at one producer
lane, lower-WRITE submission at one immutable slot, and ID63 coalescing at an
eight-block cap. The depth-two path and the settled runtime selectors are
retired from current source.


## Alpha.29 work-conserving dispatcher benchmark

ID83 adds no public command or benchmark-only selector. The ordinary `make test`
storage envelopes remain the decision surface, and the SIMD qualification
matrix remains unchanged: SSE2/AVX2/AVX-512 objects on x86_64, NEON on arm64,
with runtime execution only when the host advertises the ISA.

Owner report `5f867aa81fce` qualifies exact source `5edcb2981573` across all
five stages. The short-window/service-dry refinement fixes the specific request
geometry path identified in `b4bc5e0ba965`: fast mixed async IDLE closes fall
681.6 -> 0.6, `prep_ordered_raw` falls 2751.6 -> 1001.6, lower WRITE bytes
40.68 -> 38.13 MB, and lower WRITE requests 2678.8 -> 2444.4. Explicit
PACK_READY cause accounting now reports only 25.4 BURST_TARGET closes and
1129.2 SERVICE_DRY closes.

Fast sustained scaling also improves. QD4 async-minus-sync throughput moves from
-28.1% (95% CI -37.4..-18.7) to -6.55% (-12.45..-0.65); its lower-request
change is now unresolved at +17.1% (-6.17..+40.44). QD8 is +4.22%
(-3.95..+12.39) and QD32 +1.77% (-4.83..+8.37), both statistically neutral.
The two-record ping-pong diagnosis is therefore confirmed, but QD4 is not yet
fully recovered.

The geometry gain does not translate into a fast-mixed service promotion.
Same-source fast mixed async is 37.22 MB/s versus 37.86 sync, or -1.68%
(95% CI -4.75..+1.39), while lower requests remain +30.0%
(+27.3..+32.8) and lower bytes remain about +5.3% versus sync. The previous
`b4bc5e0` report had a confirmed +13.9% async/sync service gain. Cross-report
raw throughput is nearly unchanged (62.88 -> 62.39 MB/s), so the large async
drop is unlikely to be explained solely by host-speed variation, although
cross-report scheduler/CPU attribution remains non-comparable by policy.

The new idle attribution makes the remaining cause concrete. Fast mixed async
records 679.41 ms accepted lower-idle wall: 621.35 ms undersized-batch retention,
54.71 ms worker-unscheduled, 0 ms preparation-head wait and 3.35 ms remaining
active no-ready work. The separate post-lower diagnostic is 17.29 ms. K=1 ready
wait remains zero. The next experiment therefore targets undersized retention,
not more preparation or lower-WRITE concurrency.

A bounded next policy is to preserve retention for 1..3 records but permit a
proven-dry retained window with at least one complete four-record SWZ pack to
close as SERVICE_DRY below a larger learned target. Four records is an existing
format/packing boundary rather than a new timing heuristic. Accept it only if a
new owner `make test` recovers fast mixed useful service, removes the remaining
significant QD4 deficit, preserves the current request/byte improvement, and
keeps QD8/QD32 plus slow/SD evidence non-regressing.


## Automatic plots for each computer

`make test` publishes its report and then refreshes only that computer's plots.
The terminal prints the local index path under
`build/history/<architecture>-<host-digest>/index.md`. Each report records a
hashed OS machine identity; history is recovered from committed report revisions
so uploads by other computers do not mix their measurements or erase prior runs.
Only complete PASS reports with the same identity and architecture are plotted.
Legacy reports without this identity remain separate. An OS reinstall changes
the history identity; cloned systems need distinct `/etc/machine-id` values.
Install Python Matplotlib on each test computer. Rendering failures are reported
as `NOT UPDATED` with a local diagnostic log, independently of qualification.
Plots are local generated artifacts; report publication keeps them reproducible.


### Memory-backed lower-device allocation scope

The ID157 native owner profile observes null_blk backing-page allocation,
initialization and locking inside lower submission. These are part of attained
RAM-model service, not automatically swapz packing or dm_io descriptor costs.
Ordinary tests retain their fresh-owned-device protocol; ID36's both-device
prewarm is a separate resource constraint. Any materialized-backing sensitivity
study must treat raw and target backing identically before timing, preserve
fresh target/allocator state and matched inputs, and retain a separate protocol
series. Do not replace qualified history or claim physical NVMe fidelity or a
RAM-bandwidth bottleneck from allocation ancestry alone.


ID158's fixed matched materialization study passed all byte oracles with
unchanged product C. Its persistent normalized estimate was +9.07%, but n5<7
and adjusted sign p0.1875 failed the declared direction criterion despite a
positive paired-t interval. SATA/fast were inconclusive; secondary latency
trade-offs and resource limits remain explicit. Preserve fresh-backed canonical
qualification and keep materialized observations in their separate protocol.
The study motivates mechanism/residual-owner attribution, not a product gain,
RAM-bandwidth diagnosis or a replacement of historical raw controls.
