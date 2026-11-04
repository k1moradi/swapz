# Historical benchmark experiments and decision memory

These sections are reproduced verbatim from `docs/benchmark.md` Git blob
`716fa9bcacaa827e082f6b8eec41752da01e71cf`. The source-bound measurements, former policy statements,
confidence intervals, and proposals below are historical evidence, **not**
current production requirements, optimization authorization, or a current-source
PASS. In particular, the former ID62 physical-device restriction is superseded
by the current [operating context](../AGENT_CONTEXT.md) and
[ROADMAP](../ROADMAP.md#optimization-evidence-table).

## Old owner matrix

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
that the candidate crosses. Rescue is fixed on for emulated-device performance
qualification; the module-level `delta64_rescue=0` remains debug/compatibility
only. Current rescue writes DELTA64_SHUF8 (delta64, eight byte planes, LZ4), while
the historical ID67 timings below measured plain delta64. ID117 records the
shuffle evidence and pending full-matrix/x86 execution gates.

Earlier loaded enabled-policy evidence observed eligible pages but zero
classifier passes, transform attempts or adoptions, which justified the
default-off policy. The current predictor-first route later passed a
controlled positive-fixture rescue A/B with 4096 direct adoptions, -27.04%
lower WRITE bytes and +5.15% useful WRITE throughput. That is historical
synthetic evidence rather than representative swap prevalence; the owner has
since made the delta64 + DELTA64_SHUF8 + LZ4 stack a fixed-on requirement for
all emulated-device performance work. The following historical/native controls
continue to measure routing quality
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
| Delta64 rescue | Fixed on for every emulated device with DELTA64_SHUF8 and LZ4; predictor-first route is qualified on controlled positive content. | Reopen only for a codec/format correctness issue or a repeatable absolute service/CPU regression; do not reinstate rescue-off performance A/Bs. |
| Adjacent READ coalescing | Keep default-on, exact 2..8 ranges, zero padding, fixed eight-block cap. | New device/workload evidence shows a service regression or a larger cap has a measurable opportunity. |
| Same-extent standalone READ grouping | Rejected/retired; shared caches remain. | A new cache/layout regime creates a measured request opportunity not covered by ID63. |

Do not repeat a settled A/B merely because the detailed narrative was removed
from this file. Reopen it only under the condition above or the corresponding
ROADMAP row.


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

Delta64 rescue + `DELTA64_SHUF8` + LZ4 is fixed on for every emulated device
by owner decision after the qualified positive-fixture evidence. Standard,
storage-envelope, sustained-WRITE and development sessions all verify that
production policy; no current performance path pins rescue off. Production
ordinary LZ4 is fixed at acceleration one, the delta64 second LZ4 pass at
acceleration four, delta64 preparation at one producer lane, lower-WRITE
submission at one immutable slot, and ID63 coalescing at an eight-block cap.
The depth-two path and the settled runtime selectors are retired from current
source.



## ID158 fixed matched materialization

ID158's fixed matched materialization study passed all byte oracles with
unchanged product C. Its persistent normalized estimate was +9.07%, but n5<7
and adjusted sign p0.1875 failed the declared direction criterion despite a
positive paired-t interval. SATA/fast were inconclusive; secondary latency
trade-offs and resource limits remain explicit. Preserve fresh-backed canonical
qualification and keep materialized observations in their separate protocol.
The study motivates mechanism/residual-owner attribution, not a product gain,
RAM-bandwidth diagnosis or a replacement of historical raw controls.

## Audit-migrated residual benchmark narrative

These passages were still present in the active benchmark after the first
historical migration. They are reproduced verbatim from the same
`docs/benchmark.md` source blob named at the top of this archive. Their
qualification state and source-pinned chronology are historical; the active
benchmark and canonical ROADMAP/testing standards define current requirements.

### Partial extent residency before qualification

The current unqualified candidate also retains successfully read payload blocks
from one immutable 16KiB extent so sequential sibling records do not re-read a
block already present in `read_scratch`. This is a duplicate-I/O elimination
experiment, not yet evidence that the faster packed-read verdict becomes
FASTER. The next owner run must report actual lower READ bytes/requests and
latency before any such claim. It also reports
`batch_snapshot_crc_wall_ns` for the unchanged full-transaction pause/resume
CRC so ID 12 can be judged from measured cost rather than estimated hash bytes.

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

