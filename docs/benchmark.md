# Benchmark Standard

**Immutable naming policy (read before every prompt):** The project is `swapz`; the kernel module is `dm-swapz.ko` (loaded as `dm_swapz`); the Device Mapper target is exactly `swapz`; and the module alias is `dm-swapz`. Never put implementation-generation numbers in product, module, target, source-path, report, workflow, helper, or schema names. `SWAPSPACE2` is the only real backing format. `SWZ` names the internal extent-packing design, not a partition format; legacy persisted extent descriptors are migration debt, not an accepted disk identity.

**Three-tier test policy:** `make fast_test` is development-only and never qualifies or publishes `test_results.json`; `make test` runs the algorithm/RAM path and returns INCOMPLETE (nonzero) until physical source/run/target admission is qualified; `make test_full` retains all rootless DKMS/systemd integration and RAM qualification. Both privileged tiers report BLOCKED (nonzero) if noninteractive privilege is unavailable. RAM/integration PASS cannot certify physical storage or cold-boot production acceptance. Private scripts and CI jobs are implementation details, not operator interfaces.

Both qualification tiers retain the loaded RAM algorithm benchmark matrix.
`make test_full` also includes rootless package/systemd integration. Neither
RAM result is physical-device performance or endurance evidence.
Production compressed extents are now payload-only and their descriptors are
RAM-authoritative. That implementation change does not by itself qualify real
backing: the module's immutable `physical_ram_metadata_qualified` load token
defaults off and may be enabled only by an evidence-validating loader for the
same exact-source artifacts that passed loaded algorithm/RAM qualification.
Physical throughput, latency or endurance evidence additionally requires
matched byte-exact readback, GC/fault/concurrency coverage, RAM-budget evidence
and unchanged SWAPSPACE2 block-zero verification. Treat older physical
benchmark reports as historical; do not extrapolate null_blk figures to
ordinary SWAPSPACE2 partition performance.
New physical trials bind `raw_header_preservation_required=True` into
immutable recovery-state comparisons: a later record removing or changing this
claim is rejected. Older journals where both snapshots lack the claim remain
historical recovery evidence, never authority to rewrite a current partition.

## Ordinary swap and RAM-metadata qualification boundary

A physical or VM device comparison must use a positively identified partition
already formatted as `SWAPSPACE2`. Record and compare the exact first 4096
backing bytes before/after admission, workload, failure cleanup and normal
swapon restoration. Do not run `mkswap` on a backing partition, publish
`SWAPZ001`, write a raw header, or require a reboot; only the ephemeral
swapz Device Mapper device may receive `mkswap`. A successful trial must
offer the owner a keep-swapz/restore-ordinary choice instead of implicitly
tearing down swapz. A failed or interrupted trial must fail closed on
uncertain device ownership, without raw-header rewriting.

The new data-only 4/8/16KiB extents must carry compressed payload bytes only;
all descriptors, offsets, generations, CRCs, mapping and GC state reside in
bounded RAM. Benchmark both this RAM footprint (allocated/peak/failed
allocations) and lower READ/WRITE requests and bytes, including GC and flush.
Header/descriptor-read cache hits from the previous on-media codec are not
valid evidence of a metadata-free backing path. Paired workloads must include
byte-exact readback, overwrites, DISCARD, partial I/O, high occupancy and
mixed concurrent reads/writes. Current synthetic SWZ extent results remain
legacy baseline measurements until the migration and current-source loaded
checks pass; they never establish physical partition acceptance.

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
win. Internal sync/async comparisons may explain mechanism; they do not turn a
result that still trails raw into a product-level performance win. Delta64 is
no longer such a feature toggle: every emulated-device benchmark uses the
production delta64 + `DELTA64_SHUF8` byte-plane shuffle (byte
shuffle) + LZ4 stack, and delta64-off arms/series are excluded from current
tests and plots. Historical off/on evidence remains archival only. Mean-value
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

The former source-bound delta64/Core-2 baseline and successor measurements are
[archived verbatim](handoff/historical-benchmark-qualification-narratives.md#production-delta64-attribution-and-core-2-cache-baseline).
They are historical comparison evidence, not a qualification of current `main`.

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

The source-pinned owner matrix and its historical confidence intervals are
[archived](handoff/historical-benchmark-experiment-memory.md#old-owner-matrix).
A PASS for that source does not qualify current `main`.

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

Partial 4-block extent residency is qualified production behavior (ROADMAP
ID45), not a pending experiment. Successfully fetched 4KiB blocks from the
current immutable extent may remain resident and suppress duplicate sibling
reads only until an authority-changing mutation invalidates them. Normal
generation, descriptor and payload-CRC validation remains mandatory. The split
`batch_snapshot_crc_wall_ns` timing is attribution only: pause and resume still
hash the complete transaction and do not change publication semantics.

## Current directional result

The former ID63 directional results are
[archived verbatim](handoff/historical-benchmark-qualification-narratives.md#current-directional-result).
This heading remains for reference compatibility; its old qualification claim
is not a current-source result. Consult the source-bound
[test report](../test_results.json) for current evidence.

## Confirmation gate

ID63 remains the promoted adjacent-request confirmation surface. Fast and serial
runs use five matched rounds that vary only `read_coalesce=0/1`; independent
READ fan-out stays fixed on in both arms. Report paired 95% confidence intervals
for useful READ throughput, p99, lower bytes and lower requests. The merge-off
arm must emit zero ID63 adjacency/coalescing activity, while the merge-on arm
must keep `parallel_read_coalesce_extra_blocks=0`.

Independent READ fan-out is fixed-on production infrastructure. The retired
ID39 helper workqueue, standalone same-extent grouping and fan-out routine A/B
must remain absent; do not restore a retired selector to reproduce old
experiments.

Multi-page DISCARD retains all-or-nothing
generation/mapping/shared-extent-liveness validation with no per-physical-block
discard epoch/count arrays. The temporary live-ref accounting must be fully
restored before either error return or commit.

## Deferred idea evidence

The [ROADMAP optimization evidence table](ROADMAP.md#optimization-evidence-table)
is the canonical classification of accepted (class 1), refuted/retired
(classes 2/3/5), evidence-ready (class 4), and external-gate (class 6) ideas.
Historical ID38/63/79/58/59/61/62/72 results and design rationale are
[archived verbatim](handoff/historical-benchmark-experiment-memory.md#deferred-idea-evidence).
Keep production mechanisms in accepted rows, including fixed-on ID63 READ
coalescing and qualified ID61b GC survivor-list accounting. The archived ID62
ban on physical benchmarks has been superseded: bounded tests on the identified
dedicated SD card are permitted only under the [current safety contract](AGENT_CONTEXT.md)
and [frozen acceptance policy](production-acceptance.json).

## ID67 predictor evidence and production route

Delta64 rescue with `DELTA64_SHUF8` and LZ4 is fixed on for all emulated-device
performance qualification. The scalar sampled classifier runs before ordinary
LZ4: score >=24 pages try rescue first, adopting results <=2024 bytes directly;
lower-score pages take the ordinary-LZ4 route and may try threshold 16 only at
an exact planner packing boundary. The module disable switch is solely for
debug/compatibility. Scalar and every compiled SIMD transform/inverse backend must
remain byte-exact, and loaded end-to-end timing—not offline ns/page—decides
promotion. Console tables label compression-only time after a transform
`LZ4 ns`; combine delta64+LZ4 in a label only when both operations are
timed. Do not use ordinal labels such as “LZ4-2”.
Keep the corresponding [production invariants](coding_standards.md)
and [qualification gates](testing_standards.md) intact.

The source-bound ID67 native measurements, classifier thresholds, routing
experiments, and backend history are [archived verbatim](handoff/historical-benchmark-experiment-memory.md#id67-predictor-evidence-and-production-route).
They establish earlier decisions, not a qualification of current `main`.

## Physical media and workload validity

The owned-RAM matrix remains useful for kernel scheduling/correctness, but it is
not a model of the dedicated SD card's flash controller, queueing, erase/program
behavior or long-duration service. The current standing authorization in
`AGENT_CONTEXT.md` permits bounded work on the positively identified selected
card; physical work is still scheduled exclusively by the host/Codex owner and
must not overlap another card user. A RAM `null_blk` result is never promoted to
physical evidence.

The existing benchmark surfaces have the following evidence boundaries:

| Requirement | Existing short replay / loaded matrix | Physical qualification addition |
|---|---|---|
| Actual swap-in-sensitive reads | No. `io-replay.py` is a block-path replay; its packed-read phase is direct block I/O and explicitly does not claim a cold first pass. | `anonymous-swap.py` faults deterministic anonymous pages under a bounded cgroup, requires workload-specific swap occupancy, then byte-verifies timed rereads with the admitted swap device as the sole active swap. |
| Anonymous-page swap activity | Representative fixtures emulate page bytes only; they never activate swap. | Three raw/swapz anonymous-swap pairs exercise real Linux swap-out/swap-in. |
| Compressible / incompressible / representative content | `medium`, `entropy`, `balanced`, and private owner-sampled representative fixtures exist. | Physical helpers bind the exact fixture SHA and metadata; filenames do not establish a content class. The v2 amendment adds a five-pair entropy-fill/entropy-churn cohort whose gate is non-regression, not compression savings. |
| Low queue depth | QD1 controls exist on RAM models. | The v2 amendment adds a five-pair QD1 balanced physical service cohort. QD8 results are not used to infer QD1 latency, serialization or synchronous-overhead behavior. |
| Sustained queues | Persistent QD1/4/8/32 write workers exist on RAM models. | Physical mixed workers are persistent and bounded; the long run uses QD16. |
| High logical occupancy | The ordinary replay pre-fills only a small working range and its Python oracle scales with logical pages. | `sustained-replay.py` maps the source-derived maximum logical capacity, fills 90%, and keeps oracle state O(queue depth + fixture pages), not O(logical capacity). |
| Repeated overwrites / GC relocation | The 4096-page loaded GC pressure oracle proves bounded synthetic correctness. | A one-hour 80%-hot-region churn phase requires positive GC victims/relocated pages, repeated segment programming, zero no-headroom skips and byte-exact final recovery. |
| Cold reads | Ordinary packed-read evidence is not a cold-cache claim. | An untouched filled tail is sampled before the final full-volume verification; its latency and independent lower READ accounting are separate from the churn interval. |
| Concurrent mixed activity | Mixed synthetic QD traces exist. | The physical service and sustained workloads use deterministic lane-owned writes with concurrent verified reads. |

### Prospective dedicated-SD acceptance contract

The frozen v1 thresholds live in `docs/production-acceptance.json`; the
prospective v2 amendment is pinned separately below. The evaluator in
`tests/runtime/benchmark/qualification.py` enforces those policies. Any
criteria change requires a new protocol, with old and new results kept
separate; a private helper is not another supported test command.

`docs/production-acceptance.json` remains the frozen v1 authority and is not
modified by new physical results. The prospectively frozen v2 extension lives
in `tests/runtime/benchmark/physical-qualification-amendment-v2.json`; it is
bound to the v1 manifest Git blob
`3a422599dee32e64811545441de7525b9479f782`. The amendment was issued before
any v2 confirmatory result. Its own amendment Git blob
`eac574fd204932e630e8bb45dca66b67c135a779` is pinned in the evaluator;
an in-place criteria change must fail and be published as a new protocol.
A v1-only evaluation keeps its historical workload set; a v2 evaluation requires
all v1 and v2 workloads, without pooling their statistics. The host scheduler must explicitly select `--protocol v2` in the private
`qualification.py` evaluator, including when all new samples have failed or
are missing, to prevent silent v1 promotion.

Two v1 short-service cohorts run on the exact card: one 50/50 synthetic
medium/entropy cohort and one immutable owner-supplied representative cohort.
Each uses five adjacent raw/swapz pairs, fixed counterbalanced arm order,
QD8/20% READs, 10% logical occupancy, 65,536 warmup operations and 1,048,576
measured operations per arm. Fixed work keeps the useful logical recipe equal
between arms; elapsed time is the throughput observation. Each arm has an
external 1,800-second safety timeout. Statistical claims use the five paired
fractional deltas and a two-sided Student-t 95% interval (df=4).

The v2 amendment adds two more five-pair service cohorts with the same fixed
work, occupancy, read percentage, arm timeout and counterbalanced order. The
QD1 balanced cohort changes only offered queue depth from 8 to 1 and uses the
unchanged v1 service acceptance profile. The incompressible cohort stays at
QD8 but uses metadata-proven entropy for both fill and churn. It deliberately
does **not** require compression savings: its paired 95% useful-WRITE lower
bound must be at least -10%, normalized lower-WRITE byte and request upper
bounds must each be at most +10%, READ/WRITE p95/p99 upper bounds at most +25%,
and measured attributed CPU/useful-byte upper bound at most +50%. Exact byte
verification, target health, provenance, screening and all-pairs completeness
remain mandatory. Every swapz service arm must end with exact integer
`failed=0` and `error=0` target status; missing, malformed or nonzero health
evidence fails the arm before it can enter paired analysis. These criteria are
prospective; a disappointing result is a
FAIL, not a reason to revise the amendment in place.

The sustained cohort is one directional raw/swapz pair over the maximum logical
capacity derived by the same reserve/segment rule as the primary manager. It
fills 90% of logical pages with metadata-proven entropy pages, churns an 80%
hot region with balanced pages at QD16/20% READ for 60 seconds of warmup plus
3,600 measured seconds, retains an untouched filled tail for cold reads, and
then verifies every occupied page. The measured phase reports deterministic
hot-page touch/rewrite coverage, and both raw and swapz must reach at least one
second-cycle hot-page overwrite; positive GC counters alone do not prove a
repeated logical overwrite.
The sustained evaluator must read the exact `gc_no_headroom_skips` status
counter, require its presence as a nonnegative integer, and enforce the frozen
`gc_no_headroom_skips_max` bound. Missing/negative counters cannot be treated
as zero skips; this is fail-closed evidence validation, not a new threshold.
It also verifies that each arm actually measured at least 3,600 seconds,
preserved exactly 60 consecutive one-minute operation buckets with matching
whole-arm READ/WRITE counts. Each bucket carries an absolute monotonic start/end
inside the measured arm, adjacent buckets must join exactly, and the evaluator
independently recomputes each bucket's useful WRITE throughput from its write
count and 60-second duration before evaluating first/last-quartile drift. Each report records the measured phase's absolute
monotonic start/end; continuous telemetry must cover those exact bounds, not
merely another hour elsewhere in the broader arm. At least one fully contained
swapz telemetry interval must show positive GC victim and relocated-page
counters. The telemetry must cover the full measured hour without gaps and
record no greater than 10-second progress gap or target failure/no-headroom
skip in any swapz interval. Logical occupancy transitions must prove
the filled 90% region remained covered through the measured end; final byte
oracle evidence must cover that occupied region. These checks cannot replace
the final full-byte verification or imply 90% *physical-segment* occupancy.
Each arm has a 14,400-second scheduler
safety timeout to include the large initial fill and final oracle. One pair is
directional evidence, never a significance claim.

The anonymous-swap cohort uses three counterbalanced pairs and three verified
read rounds per arm. The worker alternates deterministic compressible and
incompressible anonymous pages in an exact 1 GiB working set under a 512 MiB
cgroup memory.max; memory.swap.max must be unlimited or cover the remaining
512 MiB. Each round requires at least 128 MiB of
workload-specific `VmSwap`/cgroup swap plus at least that much usage on the sole
admitted swap device before timed rereads can count as swap-in evidence. Each
timed reread round must independently produce positive `pswpin`, positive
cgroup-v2 `memory.stat:pgmajfault`, positive READ bytes on the exact admitted
logical swap target, and positive READ bytes on its backing disk. The swapz arm
also pins the exact DM UUID, verifies a single `swapz` table target and its sole
lower device. Swap occupancy without these independent service deltas is not
swap-in evidence. The fault-latency sample times a one-byte first touch of each
anonymous page; deterministic page generation and the subsequent 4096-byte
Python copy/byte comparison are timed separately so interpreter verification
work is not mislabeled as page-fault service. `pswpout`, cgroup swap/current
state and cgroup event deltas are retained for attribution. The worker requires
an initially empty admitted swap device, a private cgroup without foreign
processes/descendant cgroups, a clean HEAD == origin/main at the exact source
SHA, and an unchanged swap mapper/partition identity. Positive whole-arm
pswpout, exact-target WRITE and backing WRITE independently establish swap-out.
The first-byte access histogram still includes resident pages and Python access
overhead: aggregate counter deltas cannot prove that every sampled access
resolved a major page fault. These three pairs are replicated directional
evidence, not a t-test.

For physical block service the raw arm uses the same selected partition with a
4096-byte data offset so the ordinary SWAPSPACE2 header remains untouched. It
requires no holder, mount or active-swap alias. The swapz arm requires a fresh
empty mapper whose sole holder/slave relationship is the same partition. Both
arms use the exact manager maximum logical capacity, fixture hashes, content
profiles, queue geometry and deterministic operation recipe. Independent
parent-device `/sys/block/<disk>/stat` deltas bracket only the measured phase;
lower WRITE bytes/requests are normalized by completed useful writes for the
hour-long throughput comparison.

Every physical block replay retains the measured-boundary raw lower
`/sys/block/<disk>/stat` counters, process user/system CPU and post-exec
VmHWM, exported worker-CPU boundaries, and before/after target-status counters.
Warmup completion and each lower/target/worker/process boundary carry monotonic
timestamps: warmup must finish before every measured boundary and observer
setup must finish before the worker/lower/target/process baselines. The process
snapshot is the closest CPU/RSS bracket around measured start/end; target-status
snapshots sit immediately outside that process boundary, and lower-device
statistics immediately outside the target boundary. Thus setup/warmup activity
cannot enter the physical-I/O or GC deltas. The corresponding after-snapshots
must follow measured completion. Pre/post quiet windows and the timed host-CPU
screen retain the underlying `/proc/stat`/CPU-PSI boundary snapshots; the
evaluator reconstructs busy, steal and PSI fractions and applies the frozen
screening limits instead of trusting the serialized SCREENED/EXCLUDED label.
The evaluator independently recomputes lower READ/WRITE bytes and request
deltas from 512-byte sectors, logical READ/WRITE/total MB/s, process CPU and
absolute peak RSS. It also
re-derives whole-arm GC counters and GC wall fraction from the target-status
snapshots rather than trusting the serialized aggregate, requires clean
failed/error gauges at both target boundaries, and rejects fully measured
telemetry-interval GC totals that exceed that enclosing target delta. Sustained
minute histograms
separately persist READ and WRITE bins and their combined projection, so an
altered combined tail that does not conserve the original per-operation minute
evidence is rejected. Chronology and 60 consecutive measured-minute windows
are also validated. These checks do not cryptographically authenticate a
wholly rewritten report; the campaign sealer's external artifact hashes and
source/mapper identity evidence remain necessary. Adversarial regression
fixtures mutate one evidence dimension at a time while retaining unrelated
bound chronology and identity fields, so rejection demonstrates the intended
invariant rather than an incidental malformed-arm failure. GC-window mutants
also conserve their enclosing target-counter totals before testing whether
relocation occurred inside the absolute measured window. Host-visible
lower-device bytes and requests are not direct physical NAND wear measurements.
The block arm records the exact frozen claim boundary, and the evaluator
rejects a strengthened NAND-wear claim. JSON numeric parsing also rejects
NaN, Infinity and overflow exponents (for example, `1e999`) before the
reported values can enter qualification.

Every physical arm records useful READ/WRITE throughput, p95/p99 and maximum
latency, replay CPU plus exported swapz worker CPU, host CPU/PSI context, replay
RSS, a separately measured mapper metadata/target peak-RAM observation, lower
READ/WRITE bytes and requests, cold-read lower I/O, GC wall/victims/relocation,
allocator probe cost, repeated segment programming and measured-interval-only
maximum forward-progress gap. Sustained minute buckets additionally retain
combined/read/write p95 and p99, operation counts and cumulative deterministic
hot-page overwrite coverage. During duration-bounded sustained work, a
low-rate one-minute sampler records host CPU/PSI, lower-device READ/WRITE
bytes/requests and per-minute GC counters, including role rotations, without
polling the replay hot path. Boundary target snapshots retain allocator
cursor/reserve/victim state. The explicit occupancy-transition records describe
logical coverage after successful deterministic writes, not live physical
segment utilization. The maximum no-progress gap includes trailing measured
fsync stalls; any available interval samples, observer-overhead summary and
the primary failure reason are retained on replay failure, including when the
telemetry sampler itself is the standalone failure. SIGTERM/SIGINT received by either physical
benchmark worker are converted into explicit FAIL evidence when Python receives
the signal. Worker and campaign JSON publication is atomic and create-only:
complete 0600 bytes are fsync'd before the final name is linked, and an existing
file or symlink is never followed or replaced. A failed storage write removes
its private temporary inode instead of exposing partial JSON. A later invocation
therefore cannot erase an interrupted attempt. Physical acceptance latency
uses 16 sub-buckets per power-of-two range, bounding percentile bucket width to
6.25% so the 25% p95/p99 gates are not dominated by coarse quantization.
Block-service, cold-read, sustained-minute and anonymous-swap evidence persists
the nonzero histogram bins plus exact sample count and maximum. The evaluator
reconstructs every acceptance-critical p50/p95/p99 from those bins; editable
percentile summaries cannot independently promote a result. The swapz scheduler samples
`/proc/meminfo` every 100 ms from a one-second target-absent pre-create
baseline through mapper creation, the sustained workload, ordinary mapper
teardown and at least two seconds with the exact mapper UUID observed absent.
The trace keeps the kernel-reported `MemAvailable`, `SUnreclaim` and
`VmallocUsed` KiB integers plus UTC/monotonic timestamps and
mapper-presence state. The qualifying peak is derived as median(pre-create
`MemAvailable`) minus the minimum `MemAvailable` from initialization start
through the last mapper-present teardown sample, so pre-publication constructor
allocations remain charged; the final target-absent second must recover to the
baseline envelope.
RAM samples labeled GC must overlap sustained telemetry intervals whose
exported `gc_wall_ns`, `gc_victims` or `gc_pages` counter advanced.
The same host sampler surrounds the raw control so unrelated host drift is
visible. This is a whole-host upper-bound
observation, not exact per-allocation attribution; compiled array-size evidence
remains complementary and cannot substitute for it. The fixed ceilings are 128
MiB absolute post-exec replay-process peak RSS through measured completion and
1.25 GiB for metadata plus target peak RAM. Replay RSS uses the kernel's
`/proc/self/status` `VmHWM` rather than inherited `ru_maxrss`; bounded strict
parsing fails closed if that Linux metric is unavailable. Measurement-boundary
VmHWM growth is retained as a diagnostic, but setup-time allocations within the
replay remain charged to the gate.

CPU attribution has explicit boundaries. `measured_cpu_seconds_per_useful_byte`
is replay/workload-process user+system CPU plus swapz worker CPU exported by the
target where available; it is **not** whole-swapz CPU. Block softirq, unrelated
kernel workers and other host work are not charged to that process/worker sum.
Host-wide CPU ticks and PSI are reported separately and include swapz, the
kernel and unrelated background activity, so they are context rather than a
swapz-only cost. Process-only CPU must never be described as whole-swapz CPU.
The anonymous worker additionally reports process-only CPU for deterministic
fill and each reread/verification round; these are diagnostic phase splits and
do not replace the frozen whole-arm CPU acceptance metric. Sustained one-minute
telemetry reports its own sampling wall time, sampler-thread CPU and child-
process CPU (including read-only `dmsetup status` where applicable). Sampler
thread CPU remains inside `RUSAGE_SELF` and therefore remains charged to the
frozen replay-process CPU metric; child-process CPU is reported separately and
is not charged. No observer cost is subtracted post hoc from acceptance. These
diagnostics must be considered when correlating minute-level GC events with
service drift.

A 200 ms quiet window immediately before and after each arm must have busy
fraction <=25%, CPU PSI `some` <=5% and steal <=1%; timed-arm steal must also be
<=1%. Across each five-pair service cohort, raw useful-WRITE max/min spread must be
<=10%. A noisy, missing-counter, failed or excluded sample is retained with its
reason and is never automatically retried. Fewer than all prospectively fixed
pairs is incomplete evidence. The evaluator counts **all recorded attempts**:
additional failed/excluded attempts cannot be hidden behind a complete set of
passing replacements. Pair IDs must be distinct within each workload, every
attempt must match the same exact source SHA (including its raw/swapz arms),
and mixed-source campaigns are incomplete rather than pooled. Pair artifacts
are not trusted as editable summaries: the evaluator re-derives their deltas,
intrinsic exclusions and PASS consistency from the embedded raw/swapz arms.
For block replay, it independently recomputes useful WRITE throughput and
normalized lower WRITE bytes/requests from elapsed measured seconds, completed
READ/WRITE operation counts and parent-device WRITE counters. It reconstructs
the CPU/useful-byte metric from measured process user/system plus exported
worker seconds, reconciles the absolute Linux VmHWM, process peak,
measurement-start HWM and diagnostic growth, and re-derives occupied/hot page
counts plus the deterministic operation-recipe digest from the recorded
logical geometry, fixture hashes and seed. READ/WRITE latency summaries must
exactly match their serialized sparse histograms and recorded operation counts.
Anonymous arms likewise re-derive useful READ throughput, normalized lower
WRITE/READ accounting and attributed CPU from raw byte, request, round-duration
and CPU components; aggregate and per-round sparse latency histograms must match
the exact page/round geometry and oracle coverage.
Missing, nonfinite, negative or contradictory counters never qualify, even
when favorable normalized fields are supplied. Fixed-work service arms must
complete the specified operation count, not just echo the requested count.
JSON evidence decoding rejects duplicate object keys and non-standard
NaN/Infinity constants. Contract fields are presence- and type-strict:
a missing field whose required value is JSON null is not equivalent to an
explicit null, and booleans never satisfy integer workload geometry such as
QD1.
Every attempted pair, including failed or excluded attempts, must also resolve
to one exact physical lower identity
(PARTUUID, byte size, lower major:minor and parent major:minor/model/transport)
for both block replay and anonymous swap, and all attempts must agree. An
excluded attempt with missing, malformed or different target identity cannot
be filtered out to make the campaign appear single-target.
The anonymous worker resolves these fields from the mapper's sole partition
slave (or the raw partition itself) and rechecks the complete identity at arm
completion; a matching recycled major:minor alone is not same-card evidence. Physical block replay arms now retain a monotonic begin/end interval
and boot ID. The evaluator proves the selected raw-first/swapz-first order from
non-overlapping actual intervals and requires matching boot IDs, not merely
the user-supplied order label. The campaign sealer also compares each arm's
boot ID with its host-boundary snapshots. Missing or malformed chronology and
parent identity exclude the pair. Anonymous arms retain the same chronology
and boot binding; they cannot borrow an earlier boot's measurements.
Rootless evaluator fixtures provide synthetic arm timestamps and a boot ID
so that otherwise valid anonymous acceptance examples exercise the same
fail-closed chronology requirement rather than bypassing it. The
physical replay, evaluator and campaign snapshot use the same production
PARTUUID grammar: 8..64 characters, hexadecimal groups separated only by
single internal hyphens, at least eight hexadecimal digits, normalized to
lowercase before the admitted identity is recorded. The
campaign sealer independently binds that evaluator identity to the admitted
partition in the boundary host snapshot. A mismatch blocks a PASS but failed or
excluded artifacts remain sealable evidence. These are evidence-integrity
checks and do not change any frozen performance threshold. Acceptance counters
and byte/page quantities are type-strict integers; JSON strings and booleans are
malformed evidence and cannot satisfy a numeric gate.

For each five-pair service cohort, PASS requires the paired 95% interval lower
bound for useful WRITE to be at least +5%; interval upper bounds for normalized
lower WRITE bytes and requests to be at most -10%; READ and WRITE p95/p99 upper
bounds to be at most +25%; and the measured CPU-per-useful-byte upper bound to
be at most +50%. An interval crossing a threshold fails that threshold; means
alone do not promote a result.

The sustained directional pair additionally requires swapz/raw useful WRITE
>=1.05, normalized lower WRITE bytes and requests <=0.90, READ/WRITE/cold-read
p99 ratios <=1.25, last-quartile/first-quartile throughput >=0.75, the analogous
p99 ratio <=1.25, GC wall <=20% of measured wall time, zero GC no-headroom
skips, positive GC relocation and segment programming, zero target failure,
zero oracle mismatches and no >10-second interval without forward progress.
The anonymous cohort requires every pair to keep swap-in p95/p99 <=1.25x raw,
useful read service >=0.80x raw, normalized lower WRITE bytes/requests <=0.90x
raw, measured attributed CPU/useful-byte <=1.50x raw, the 128 MiB swap-occupancy
floor, positive per-round `pswpin`/cgroup-major-fault/exact-target-READ/backing-
READ evidence and zero byte-oracle mismatches.

**Physical campaign orchestration contract (not a current-host PASS):** shared
physical orchestration must enumerate the
frozen v1 contract plus the v2 amendment, preserve the prescribed pair order,
pass the exact DM UUID into the swapz anonymous arm, use a worker-only private
cgroup, explicitly request `--protocol v2` for v2 qualification, serialize on
the existing physical-performance lock, and retain every arm/pair JSON plus
exclusion/failure reason. It must not rerun a failed/excluded pair to replace it
with a passing sample. Physical execution is scheduled exclusively by the
host/Codex owner; no VM/fallback run is an acceptable substitute and no two
host experiments may overlap.

The read-only [private evidence helper](../tests/runtime/benchmark/physical-campaign-evidence.py)
is the evidence boundary for that scheduler, not a scheduler or public command.
Its `snapshot` subcommand requires `--source-sha`, `--device` and `--result`;
the scheduler captures one observation before the first arm and one after the
final arm. Snapshots bind the clean
HEAD/origin-main source to kernel/CPU/affinity/frequency-policy, memory,
admitted-device size/model/transport/queue/scheduler, direct holders, block
ancestry, swap and mount inventories, PSI, thermal-zone readings and loaded
swapz module parameters. In addition to requiring the full mount/swap
inventories to remain stable, the admitted partition itself must be quiescent
in both boundary snapshots: no direct holder, no active-swap row with its exact
major:minor, and no mount with its exact major:minor. After the [private evaluator](../tests/runtime/benchmark/qualification.py#L1989-L2003)
receives `--protocol v2` and all pair-report inputs and writes its summary,
the scheduler invokes the evidence helper's `seal` action with both snapshots,
the summary and **every** pair JSON, including failed/excluded attempts. Sealing is
create-only, requires distinct before/after/summary/pair input files and
timezone-aware nondecreasing snapshot times, re-runs the qualification evaluator
from the supplied pair JSONs, and requires the regenerated summary to match
exactly. It hashes the frozen acceptance manifest, prospective amendment and
evaluator. FAIL/INCOMPLETE evidence may still be sealed when pair/source
provenance is inconsistent so the invalid campaign remains auditable; a PASS is
blocked unless all pair/summary source identity matches the exact host source.
Stable source/tree, full kernel identity including one unchanged boot ID and
nondecreasing host uptime, CPU model/policy/affinity, total RAM, mount and swap
inventories, device and parent identities/queue/scheduler and swapz module
cleanup state are independently required for PASS. The sealer retains
the separately validated target-RAM lifecycle trace including teardown, and
requires the sustained mapper's logical page count to match the manager's
source-derived *maximum*, rather than accepting merely a mapper that fits
the physical partition. The resulting
campaign JSON is the machine-readable provenance index; preserving the original
arm/pair files remains mandatory.
This methodology change intentionally does not add a second public test
command.

Reduced host-visible lower WRITE bytes/requests are a physical I/O-cost result.
They must never be described as directly measured NAND wear, write amplification
or endurance improvement.

## Settled experiment memory

Use the [ROADMAP optimization evidence table](ROADMAP.md#optimization-evidence-table)
as the single anti-retest index, including each class and reopen condition.
The older benchmark-specific decision table is
[archived verbatim](handoff/historical-benchmark-experiment-memory.md#settled-experiment-memory)
for auditability. Do not rerun a settled A/B solely because its chronology is
absent from this active standard; retain accepted production behavior.

## Current qualification protocol

Current benchmark work must preserve these contracts:

- **Ordinary LZ4:** production acceleration is fixed at one. The native
  1/2/3/4 sweep remains only a byte-exact codec/geometry regression check.
- **Delta64:** rescue + `DELTA64_SHUF8` + LZ4 is fixed on for emulated-device
  qualification. The module disable switch is for debug/compatibility only,
  never a benchmark arm or plot series. Classifier, SIMD and timing-label
  rules live in [the ID67 production route](#id67-predictor-evidence-and-production-route);
  loaded wrapper-inclusive timing remains authoritative.
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

The former ID73/ID78 source-bound measurements and proposed experiments are
[archived verbatim](handoff/historical-benchmark-experiment-memory.md#current-evidence-cycle).
They are not the current work queue or a qualification of current `main`.
For current priorities, read the [production decision order](AGENT_CONTEXT.md#current-decision-order),
[ROADMAP evidence table](ROADMAP.md#optimization-evidence-table), and exact-source
[test report](../test_results.json) before scheduling another performance test.

## Alpha.29 work-conserving dispatcher benchmark

The historical ID83 measurements, confidence intervals and proposed follow-up
are [archived verbatim](handoff/historical-benchmark-qualification-narratives.md#alpha29-work-conserving-dispatcher-benchmark).
This source-bound experiment is not a current release or optimization gate.

## Automatic plots for each computer

`make test` publishes its report and then refreshes only that computer's plots.
The terminal prints the local index path under
`build/history/<architecture>-<host-digest>/index.md`. Each report records a
hashed OS machine identity; history is recovered from committed report revisions
so uploads by other computers do not mix their measurements or erase prior runs.
Exact-computer selection (`--host-id`) requires a complete five-stage PASS.
A report with the exact `host_identity` is accepted directly; a legacy report
that is not an exact identity match enters that computer's history only when its
full report SHA is owner-confirmed in
[host-history.json](handoff/host-history.json) and its architecture, online-CPU
count and required backend signature still match.

Audited x86 profile selection (`--host-profile`) is a separate cohort rule: the
full report SHA must be in that profile's allowlist, all five stages must PASS,
the configured CPU count must match every benchmark arm, and scalar, SSE2, AVX2
and AVX-512 backend evidence must be present. If such a report carries
`host_identity`, it must also be x86_64 and match the profile's host digest.
The default historical ARM64/NEON VM cohort is intentionally weaker: it requires
overall PASS, seven observed online CPUs and an executed NEON backend, so some
older reports can lack a complete stage list or immutable host identity. That
legacy cohort is descriptive only, not exact-host qualification or evidence that
old reports qualify current `main`. A shared ISA/CPU count never automatically
merges a legacy report into an exact-computer history. An OS reinstall changes
the history identity; cloned systems need distinct `/etc/machine-id` values.
Install Python Matplotlib on each test computer. Rendering failures are reported
as `NOT UPDATED` with a local diagnostic log, independently of qualification.
For a failed qualification, follow the [report triage path](README.md#diagnose-the-first-record)
to the first failing stage or post-stage gate before interpreting optional plot
output. Plots are local generated artifacts; report publication keeps them reproducible.


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


The source-bound ID158 materialization measurements and their uncertainty are
[archived verbatim](handoff/historical-benchmark-experiment-memory.md#id158-fixed-matched-materialization).
Ordinary fresh-backed qualification and symmetric raw/swapz treatment remain mandatory.
