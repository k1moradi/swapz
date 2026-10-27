# Coding Standards

**Immutable naming policy (read before every prompt):** The project is `swapz`; the kernel module is `dm-swapz.ko` (loaded as `dm_swapz`); the Device Mapper target is exactly `swapz`; and the module alias is `dm-swapz`. Never put implementation-generation numbers in product, module, target, source-path, report, workflow, helper, or schema names. `SWZ` is the current unversioned on-disk format identity; do not assign a format version until an incompatible format boundary is justified.

**Single official test command (read before every prompt):** Run `make test` at the repository root for every supported swapz test and benchmark. A complete run must report BLOCKED (nonzero) if safe noninteractive privileged qualification cannot run. Do not create, publish, recommend, or document alternative test commands. Private scripts and CI jobs are implementation details, not operator interfaces.

## Priority

More than half of ongoing development engineering time should concern production Linux kernel C: debugging, profiling, algorithms, I/O ownership, mapping authority, GC and measured performance. Do not invent tests or infrastructure when a direct C fix is the work that matters. Python and shell are thin qualification glue.

## Source and naming

Active product C/C++ and headers live under `src/`; test-only code lives under `tests/`; maintained Markdown lives under `docs/`; packaging code lives under `packaging/`. Do not recreate parallel `kernel/`, `userspace/`, `tools/`, legacy source trees, alternate research modules or historical models.

Use `swapz_` / `SWAPZ_` for implementation identifiers and `swapz` for the product/candidate. The Device Mapper target is exactly `swapz`; the module alias is `dm-swapz`. SWZ may appear only when discussing the current unversioned disk format.

## Kernel C rules

Use Linux-kernel-style C, kernel types/APIs, explicit ownership and checked arithmetic. Keep functions cohesive, allocations bounded, stack use modest and concurrency ownership obvious. Avoid recursion, hidden allocations, libc/C++ in the module and duplicated state machines.

Every accepted BIO must have exactly one completion owner. Never publish a mapping before all required lower data and ordering work succeeds. Preserve generation/CRC checks, PREFLUSH/FUA ordering, same-page dependencies, discard semantics, suspend/drain safety and fail-closed teardown.

Allocation and GC must never reuse a possibly live or partially written extent. GC may relocate only current authoritative records and must account for its lower READ/WRITE cost.

## Performance work

State a concrete production-C hypothesis before changing policy. Measure useful logical work and independent lower bytes/requests. Request reduction that loses useful throughput can still be useful diagnostic evidence, but is not a win by itself. Read p95/p99, CPU, RAM and GC are part of the result.

The `make test` stdout report is a decision artifact, not a metric dump. Every
table must print a concise **Evidence -> Goal implication -> Verdict** reasoning
chain after its legend and numeric interpretation. Product-facing tables must
connect useful READ/WRITE, latency and lower-device bytes/requests to the vision;
internal/native/model tables must explicitly say when they are diagnostic or
supporting only. Lower WRITE bytes/requests are the host-I/O endurance proxy.
Lower READ traffic is an efficiency/performance result, and logical segment-open
spread is allocator fairness; neither may be mislabeled as physical NAND wear
evidence. A trade-off or confidence interval crossing zero must remain visibly
unresolved rather than being summarized as a win.

Remove diagnostic branches and counters after they answer their question. A rejected experiment must not keep consuming hot-path CPU or schema surface.

A benchmark labeled sustained QD must pre-create its worker set before the
timed interval and must not use per-I/O `Future` submission, main-thread
completion handoff or a full-QD barrier between successive writes. Write-only
saturation traces must give each persistent lane disjoint logical-page
ownership while preserving that lane's operation order, so unconstrained
cross-lane completion cannot change the final image. A QD-wave driver may be
kept only when explicitly labeled as burst/wave evidence.

## Dead-code rule

Keep the working tree centered on code that ships or directly qualifies the current product. Historical reproduction belongs in immutable Git history. Delete alternate implementations, obsolete compatibility harnesses, unused models, stale workflow gates and historical test-only backends once no active product invariant depends on them.

Before deleting production code, identify all current callers and preserve necessary behavior in direct production-C tests. Never restore dead product code merely to satisfy an orphaned test; delete or rewrite the stale test when its subject no longer exists.

## Change discipline

Work directly on `main` unless the owner explicitly authorizes another branch. Check the current remote head before every write and use lease-protected fast-forward updates. Keep commits small enough to review. Do not force-push or overwrite concurrent work.

Every implementation task updates the relevant governing standard in the same commit. README/VISION change only when user-facing structure or acceptance criteria change.

## Host safety

Never reboot, `swapon`, `swapoff`, mount test storage, force-remove mappings or touch physical/unowned devices. Loaded development uses only positively owned RAM-backed `null_blk` with exact identity checks and ordinary teardown/quarantine.


### Deferred content-sharing and concurrency experiments

Same-filled-page and dedup optimizations must preserve the existing authority
model rather than create hidden aliases. A nonzero same-filled representation
needs an explicit type/format decision and exact 4KiB reconstruction; do not
reuse the zero-page encoding for nonzero values. Exact-content dedup requires
bounded ownership/refcount state, full-byte verification before sharing,
generation-safe copy-on-write on overwrite, and GC/DISCARD accounting that
cannot free a payload while any authoritative mapping references it. Hash
equality alone is never sufficient authority.

READ coalescing may combine only requests already waiting behind serialized
service. It must not delay an otherwise dispatchable read, cross an ordering or
authority mutation boundary, merge incompatible generations, or share mutable
decode scratch across concurrent completions.

A future background-GC worker remains subordinate to the single publication and
allocation authority. It may not consume the last reserve, race foreground
allocation for a destination, publish relocation before lower completion, or
continue after suspend/drain/failure has revoked ownership.

Production lower-WRITE submission depth is fixed at one. Repeated paired
depth-1/depth-2 evidence did not establish a useful service benefit, so the
runtime selector, second-slot allocation and second-run append path are removed.
The sole active run retains immutable packed bytes, transaction snapshots, BIO
references and completion state through definitive lower completion and
serialized authority publication.

Any future K>1 experiment is a new architecture change, not a dormant knob. It
must restore disjoint immutable run ownership, same-page generation/order
fences, FIFO authority publication and upper-BIO completion despite out-of-order
physical completion, verified-tail-only rollback, and ordered drain across
PREFLUSH/FUA/DISCARD, GC, suspend, teardown and failure.

Physical-device support is not a coding shortcut around current safety policy.
No production/test flag may silently relax the RAM-backed owned-device gate.

## Current write-window, packing and preparation rules

These are current implementation invariants. Historical experiment sequences
belong in the ROADMAP decision table and Git history.

- **Admission:** the retired `coalesce_ms` delay must stay absent. Ordinary
  writes queue immediate work; dependencies and retained writes wake the owner
  immediately. Never add a sleep/spin/grace wait for a future arrival.
- **Finite accepted work:** a retained window may consume only BIOs already
  accepted into the worker-local FIFO or `incoming`, bounded by the existing
  64-BIO quantum. Refresh accepted queue state after synchronous copy/LZ4 work
  before deciding the current pack is isolated.
- **Proven-dry retained service:** an active accepted plain-WRITE wave keeps the
  existing eight-record pressure hand and effective learned/sampled target. Only
  after the serialized worker proves both accepted FIFOs dry, no K=1 lower WRITE
  remains active, no sampled tail target is pending, and a valid compressed pack
  is already staged may a retained window close below a larger learned target at
  the four-record floor. One-record windows keep the original pinned deadline.
  Post-PACK sampled tails two/three are not authoritative close targets, but an
  already-staged valid pack from such a suppressed tail may close SERVICE_DRY
  after the qualified 500us post-completion resubmission bound, or once an
  independent READ proves a wave pivot, provided K=1 is idle and both accepted
  FIFOs are dry. Sampled target four and larger remain one-shot finite targets.
  A prior completed chain or deferred valid pack alone must never bypass the
  four-record floor. The explicit sub-four paths require a staged valid pack and
  at least two records; they must never manufacture a one-record PACK_READY
  close. Source comments and native contracts must distinguish this qualified
  suppressed-tail exception from the general four-record work-conserving floor.
- **Retention deadline:** learned/admitted targets may shape aggregation, but
  the ordinary absolute deadline remains the hard boundary
  ($t_{\text{deadline}} = t_{\text{first}} + \text{retain\_ms} \times 1\text{ ms}$).
  ID83 has one separately qualified earlier wake: a suppressed post-PACK tail of
  two/three records with a staged valid pack may advance the existing hrtimer to
  `sample_start + 500us`; it does not extend or replace the ordinary deadline and
  it allocates no second timer. A deferred sampled singleton still uses only the
  ordinary deadline; ID53 remains rejected. Hard ordering boundaries reset
  retained scheduling evidence.
- **In-flight write reaping:** completed detached $K=1$ lower writes are reaped
  opportunistically inside the worker loop so upper BIOs receive `bio_endio()`
  immediately without waiting for the full 64-BIO quantum or retention expiration.
  Tail sampling is gated on `swapz_has_inflight(ctx)` so unfinalized completions
  never produce false empty-tail measurements.
- **Planner:** minimize lower bytes first, bounded cold-read cost second and
  extent count third. Only the adjacent lower-run writer may use the physical
  cursor/larger-class tie-break after those objectives are exactly tied.
  Default mode never adds padding bytes merely to improve alignment.
- **Scratch:** do not clear full 4/8/16KiB or 256KiB buffers when authoritative
  bytes will be overwritten. Initialize exact headers/descriptors/payloads and
  only the unused gap that can actually reach lower media. Tests should poison
  scratch so correctness cannot depend on incidental zeroing.
- **Zero elision:** scan the complete 4KiB page byte-exactly. Portable wide
  loads use `memcpy`; do not overread, allocate or cast an unaligned byte
  buffer to a wider pointer.
- **Metadata residency:** the 512-entry metadata cache remains bounded and holds
  validated metadata only, never payload authority. Mutation fences invalidate
  residency before authority changes. Set lookups cache the active epoch locally
  and avoid redundant engine field traversal. Extent geometry calculations and
  fitting use constant block-shift powers (`SWAPZ_BLOCK_SHIFT`) rather than integer division.
- **Preparation ownership:** async preparation uses one unbound producer lane.
  The ordered owner may steal only an unclaimed next preparation entry while
  holding the admission lock. Producer and ordered compression use separate
  input/LZ4 scratch and single-writer timing state. Prepared-array slots belong
  only to producer-prepared entries.
- **GC destination probing:** preserve the authority's circular
  `next_segment_probe`; collection must not restart at segment zero. A
  destination remains reusable only after the existing deadness, mapping and
  role checks succeed.
- **Diagnostics:** PACK_READY causes, tail samples, ready-wait counters and
  similar telemetry are observational unless a separately qualified policy
  explicitly consumes them. Adding a counter is not permission to change a
  scheduling decision. ID83 suppressed-tail state is worker-owned only: no
  mapper atomic or admission gate is permitted. Owner report `64f6e8e1890e`
  qualified the existing retention hrtimer's bounded 500us suppressed-tail wake
  and cache-hit independent-READ pivot; lifetime counters remain through the
  candidate qualification and are removed after that scheduling result settles.

### Settled implementation policies

Use the ROADMAP ID as the authoritative decision record. Do not reintroduce
these mechanisms as dormant knobs merely to make them easy to benchmark again.

| Policy family | Current rule | Reopen condition |
|---|---|---|
| Admission delay / microsecond grace timer (ID30) | Removed; no future-arrival wait. | New measured workload plus an ordering-safe bounded hypothesis. |
| Deferred-singleton short cutoff (ID53) | Rejected/reverted; ordinary deadline only. | Evidence disproves the feedback artifact that caused the regression. |
| K=1-busy zero-tail preservation (ID57) | Rejected/reverted; do not carry stale wave evidence. | New ownership model proves wave separation. |
| CPU-local/affinity preparation (ID7/32) | Rejected; keep unbound scheduling. | Trustworthy CPU attribution shows placement is the limiting factor. |
| Multiple preparation workers (ID16/31) | One producer lane. | Sustained preparation backlog plus measured service opportunity. |
| Lower-WRITE K>1 (ID38) | One slot; depth-two allocation/append path removed. | New device/workload proves ready-run pressure and justifies new ownership state. |
| Full-buffer zero initialization | Avoided; initialize only bytes that can be submitted/read. | Only if a new representation introduces genuinely undefined submitted bytes. |
| Final payload CRC removal (ID19) | Forbidden; retain the integrity boundary. | Equivalent fail-closed integrity mechanism. |
| Same-extent standalone READ grouping (ID60) | Retired; use shared caches and ID63. | New layout/cache evidence shows a distinct request-saving opportunity. |

Repository naming guards must not contain their own banned implementation names
as literal searchable text. The public engine, authority and codec surfaces
remain product-facing; native tests must not keep otherwise-unused wrappers or
helpers alive solely for test convenience.

### Bounded adjacent distinct-extent READ coalescing

ID63 may operate only on the already-admitted independent READ prefix. It never
waits for another BIO and never crosses a write, barrier or dependent read.
Eligibility runs only when ID63 coalescing is enabled; the disabled A/B arm
must return before any coalescing cache probe, candidate scan, private-slot work
or coalescing counter update. When enabled, first inspect the ordered owner's
direct/LRU residency metadata without copying cached blocks into private slot
scratch. If the FIFO head is already satisfied by shared cache residency, reject
in O(1) before the bounded candidate-chain scan; do not repeatedly walk the same
64-BIO prefix for cached siblings of one extent. Private slots are primed only after the exact missing
ranges prove one zero-padding coalesced lower request.

Eligibility is based on the exact lower blocks still missing for every grouped
BIO, not merely full-extent adjacency. Each selected private extent's missing
mask must collapse to one nonempty contiguous range; 2..8 selected ranges must
join immediately with no gap, remain inside one 1MiB segment and total at most
8 blocks / 32KiB. Padding or gap reads are forbidden.

One synchronous lower READ may fetch the combined span into preallocated
scratch. Those bytes are seeded only into private slot residency and are marked
unvalidated. Normal swapz_engine_read_page validation must still verify SWZ
metadata, logical identity, generation, sequence and payload CRC for every
constituent record before that seed becomes ordinary cache residency. A lower
I/O, metadata, generation, CRC, decode or upper-copy failure prevents shared
cache absorption and fails closed under the existing batch contract.

Actual combined batches, requests saved, blocks fetched and extra blocks are
separate monotonic counters. An N-extent chain adds N-1 to
`parallel_read_coalesced_reqs_saved`; extra blocks must stay zero.

Passive rejection attribution is allowed only when ID63 is enabled and the two
full extents are already physically adjacent under the same segment/size
bounds. A non-merge is classified once as cache-satisfied, noncontiguous
per-slot missing mask, adjacent-full-extents whose exact missing subranges have
a gap, or a defensive other/invariant bucket. These counters never change
eligibility, cache state, dispatch or completion. Qualification requires the
defensive other bucket to remain zero; do not force conservation against the
older passive-adjacent counter on hwq=1 because depth-one fallback can suppress
that legacy pair counter after the candidate was already observed.

### Worker scheduler-accounted CPU attribution

Keep callback wall residency and worker CPU attribution separate. At
ordered/preparation worker boundaries, sample
`READ_ONCE(current->se.sum_exec_runtime)` and accumulate nonnegative deltas in
dedicated counters. The retired ID39 helper has no worker boundary;
`read_worker_cpu_ns` is retained only as a zero-valued status compatibility
field. These samples exclude lower-I/O sleep and runqueue wall delay, but a direct
entry/exit sample can materially miss a short non-sleeping callback when the
scheduler has not updated the current entity between samples. Therefore the
counters are lower-bound diagnostics, not total or cycle-exact CPU time. Expose
separate ordered/preparation LZ4 and copy timers; reports may sum
LZ4+CRC+copy for the producer and LZ4+CRC+copy+commit-non-I/O for the ordered
path as measured non-sleeping phase floors. Floors are not total CPU either.
Do not call an unexported scheduler helper merely to sharpen this measurement.

### Synchronous READ grouping and ID63 control

The read-only `parallel_reads` and `read_coalesce` module parameters remain
evidence controls, not runtime auto-tuning policy. `parallel_reads=1` enables
the bounded grouping machinery; `read_coalesce=1` additionally permits exact
ID63 adjacent missing-range coalescing. When hardware queue depth exceeds 1
and observed backing latency is low ($< 120\text{ }\mu\text{s}$), read coalescing
yields to concurrent multi-slot asynchronous fan-out to prevent head-of-line
serialization on fast NVMe/SATA storage, while preserving exact adjacent
coalescing on high-latency or depth-1 serial media. They do not enable helper
concurrency.

The rejected ID39 `swapz-read` workqueue, per-slot work/completion objects,
queue/wait/flush dispatch and helper CPU accounting are not part of current
production code. `parallel_reads_enabled` remains in status for schema
compatibility and must be zero; `read_worker_cpu_ns` must likewise remain
zero.

`swapz_try_parallel_read_batch()` is ID63-only. The one allowed pre-scan cache
probe is the O(1) FIFO-head exact-range check: a fully cached head must return
immediately before the immutable-read prefix or candidate-chain scan. After the
prefix scan, all other rejection paths must still return before private-slot
priming and BIO ownership transfer; the bounded candidate may inspect shared
cache metadata to derive exact missing ranges, but it must not copy cached
blocks into slot scratch. Noncontiguous or gapped missing ranges remain
ineligible. Standalone same-extent slot grouping is retired;
ordinary `swapz_read()` already reuses the shared extent/metadata caches.
For a successful ID63 pair, lower-I/O/decode telemetry is committed before upper
BIO completion, but shared LRU cache absorption must occur only after every
successful upper BIO has been completed so cache memcpy is off the completion
critical path.

Fast and serial ID63 qualification keeps `parallel_reads=1` and varies only
`read_coalesce` for five matched rounds. The off arm is the ordinary FIFO read
path and must execute zero grouped/coalesced slot pairs. Dedicated ID39/ID60
loaded controls are removed after owner qualification/refutation; do not retain
dead benchmark sessions merely for historical telemetry.

### Page-local delta64 production routing and qualification

Whole-page delta64 is the only maintained predictive transform; the refuted
CL-delta, byte-delta, delta32, reset-delta64 and xor64 experiments live only in
Git history. The read-only module parameter `delta64_rescue` defaults to zero
and is snapshotted into each target at construction. The rescue-only second LZ4
pass uses the separate read-only `delta64_lz4_acceleration` parameter
(default 1, bounded 1..4); changing it must not alter the ordinary first-pass
`lz4_acceleration` policy. Both producer and ordered
write paths must bypass the rescue call entirely when disabled; no classifier,
rescue timer or rescue counter runs and no predictor scratch is allocated for
either write or read slots. Ordinary LZ4 remains active. The codec and GC retain
delta64 encoding support; reads of an encoded record require their scratch and
fail closed if it is missing. Only an explicitly enabled target may write new
delta64 records. A default-off result is not a measured classifier rejection.

When explicitly enabled, the scalar sampled classifier runs before ordinary
LZ4. Score >=24 pages run delta64 plus the rescue LZ4 first. A candidate at or
below 2024 bytes may be adopted directly and skip ordinary LZ4; a larger
high-score candidate falls through to ordinary LZ4 and is adopted only if
strictly smaller. Lower-score pages run ordinary LZ4 first and may enter the
threshold-16 packing-aware path only when the planner identifies an exact lower
uniform payload limit in a maintained extent class; adoption must cross that
limit and remain strictly smaller.
Portable unsigned,
memcpy-safe C delta64 is the mandatory correctness oracle and fallback.

Production attribution uses separate cacheline-aligned single-writer preparation
and ordered worker accumulators. Count eligible baselines, classifier passes, transform
attempts and smaller-payload adoptions; split adoptions and encoded-byte savings
between RAW and ordinary-LZ4 rescues. Only status sums the accumulators with
`READ_ONCE`; no counter lock or atomic update belongs on the page path. These
are foreground preparation attempts, including speculative work later aborted,
not committed mappings. GC relocation must not count a fresh rescue attempt.
RAW savings use 4096 bytes as baseline; ordinary-LZ4 savings use its actual
payload length. Neither is a claim of avoided physical blocks or endurance.
Rescue wall time includes classifier, transform, second LZ4 and candidate copy;
it can include preemption and overlaps existing LZ4/worker timings. Do not add
it to those timings or label it CPU consumption.

The current SHAKE-generated benchmark hard regions are negative controls, not a
positive predictor corpus. Native evidence must also construct deterministic
pointer/page-table, integer counter/timestamp, float/double, fixed-layout
struct and independently based subpage archetypes. Routing evidence must be
separate from the full transform: sample the raw page first, never count a zero
delta as positive evidence, and report false calls by negative profile.
ID67 keeps the 8-pair page-wide first stage; fewer than two points is an
immediate reject, and passing pages extend to 32 fixed strided pairs. Scalar,
SSE2, AVX2 and NEON must produce byte-identical transforms, inverse pages and
classifier scores. SIMD code lives in isolated translation units compiled with
the kernel FPU flags; ordinary DM/authority/engine/codec objects must never be
compiled with SIMD enabled. x86_64 uses SSE2 as the compatibility SIMD baseline
and selects AVX2 only with the CPU feature plus enabled YMM xstate. arm64 selects
NEON only when kernel-mode FPSIMD is available. Otherwise scalar C remains
active. Kernel dispatch is selected once at module initialization with
static_call patching, with no per-page CPU-feature branch or permanent indirect
call. SIMD entry/exit uses kernel_fpu_begin()/kernel_fpu_end() from the non-SIMD
dispatch translation unit and is process-context-only; a non-task call falls
back to scalar. Native qualification may use ISA state directly. Classifier
timing remains batched across repeated eligible-page sweeps.
Kernel predictor implementation locals must not use identifiers that collide
with Linux context macros such as `current`; use explicit value/previous names.
The retained 64-byte cacheline constant is corpus geometry only, not a retired
predictor model.

The sparse 8->32 classifier is scalar-only and must never enter kernel FPU/SIMD
state. Full-page transform and inverse remain separate static calls, but current
x86 production policy selects the same qualified ISA tier for both: AVX-512
when its CPU/xstate requirements are met, otherwise AVX2, otherwise SSE2, with
scalar fallback. arm64 selects kernel-mode NEON when available. Qualification
continues to time scalar and every compiled backend independently so a later
evidence change can alter policy without weakening byte-exact equivalence.
Thresholds are evidence, never kernel policy before measurement.

Delta64 must round-trip exactly, and every selected hardware backend must match
the scalar oracle on every classified/transformed page. Measure transform,
inverse and optional second-LZ4 cost. Feed actual compressed-length sequences into the production
`swapz_engine_plan_bounded()` and report planned 4KiB blocks/extents, RAW
rescues and packing-cliff crossings. For every router threshold, also feed the
classifier-routed delta64 lengths through the same planner and report routed
blocks/extents saved; ungated transform opportunity alone is not routing
evidence. The production transform unit is exactly one independent 4KiB logical page.
Never carry delta state across sibling records or an extent: doing so would
couple authority and force unrelated blocks into selective reads. SWZ records
encode LZ4 versus delta64+LZ4 explicitly without enlarging the 16-byte record.
The volatile mapping may pack the encoding into unused record-index bits, but
every metadata read must cross-check it. CRC covers the stored compressed
payload. Reads LZ4-decompress first and apply the selected inverse only for a
delta64 record. GC relocates the stored payload and preserves its encoding
without decode/re-encode. Raw fallback and zero elision remain separate
representations.

### Retired in-flight-zero shrink guard

Completion-aware tail sampling now returns before consuming tail == 0 while a detached K=1 lower WRITE is incomplete. Owner evidence at source 086ce15f3476 then exercised zero after-I0 shrinks and zero ID64 skips across five matched rounds, so the one-shot guard is retired. Do not restore its module parameter, policy helper, remembered flag, or loaded A/B.

For report compatibility only, guard_inflight_zero_shrink, burst_shrink_inflight_zero_skips, and burst_shrink_after_inflight_zero remain status tokens fixed at zero. They are not active state and must not influence scheduling.

### Zero-allocation DISCARD range prevalidation

Multi-page DISCARD must validate the complete logical range before committing
any mapping/generation invalidation. Shared physical extents require aggregate
liveness accounting: the serialized ordered worker may temporarily decrement
one `live_records[start]` reference per validated page, but it must restore the
exact validated prefix on both success and failure before entering the commit
loop.

Do not allocate per-physical-block epoch/count scratch for this check. The
temporary accounting pass performs no lower I/O and no mapping/generation
mutation; malformed start/class/liveness or generation overflow fails closed.
The subsequent `swapz_discard_page()` loop remains the sole commit path.

### ID36 deterministic resource-pressure qualification

The owner-only ID36 gate must establish pressure rather than assume benchmark
allocations will cross a watermark. Both owned 64MiB RAM-backed null_blk devices
are fully faulted before the pair migrates into the cgroup. The pressure helper
uses a lazily faulted anonymous mapping with a final 576MiB working set: fault
496MiB first, sample the ready-state `memory.current`, then install
`memory.high = ready memory.current + 64MiB`. Only after that boundary exists
may the helper fault the remaining 80MiB. The harness must observe a positive
`memory.events high` delta and zero OOM/OOM-kill before releasing the pair.

Keep `memory.max=896MiB`, disable cgroup swap when the controller exposes that
knob, and refuse the run when the staged final charge would violate the bounded
maximum. The final working set remains active for target construction, replay,
packed byte-exact readback and teardown. Two-times online-CPU integer burners,
capped at 32 and never below two, remain active throughout; CPU-PSI evidence is
sampled from pair release so setup activity cannot satisfy the CPU gate.
Pressure establishment is qualification setup, not useful-work performance
evidence, and may not weaken ordinary byte-exact/OOM/teardown requirements.

Replay harnesses (`io-replay.py`) running inside the pressurized cgroup must
avoid heap allocation churn in hot loops. Because the cgroup is deliberately
held above `memory.high`, thread allocations can trigger kernel throttling
via `mem_cgroup_handle_over_high()` (up to 2.0s penalty). To ensure reliable
completion within the immutable `PAIR_OUTER_SECONDS=420` budget without false
timeouts, the harness shares a single persistent `ThreadPoolExecutor` across
both the mixed workload and packed read-set verification, pre-allocates I/O
vectors (`read_iovs`, `mixed_iovs`), uses direct buffer writes (`os.pwrite()`),
avoids per-sample regex parsing in the background telemetry sampler, and
disables cyclic garbage collection during timed measurement loops. The private
ID36 packed-read path must additionally submit exactly one long-lived job per
QD lane and reuse barriers/result slots across population, sequential and
seeded-random waves; it must not allocate a `Future`/work item/list per 4KiB
I/O or construct a temporary 4MiB joined oracle. Ordinary non-pressure
benchmark submission remains unchanged so this harness fix cannot masquerade
as a production performance change.

### Foreground GC pressure and scaling telemetry

ID61 evidence must observe the existing serialized collector without changing
victim policy, allocation authority, publication order or introducing a GC
worker. Time the complete `swapz_gc_compact_one()` attempt exactly once,
including RAW callers and failed/no-headroom attempts, and time victim choice
inside that total. Do not double-account GC wall at individual call sites.

For scaling evidence, count exact loop work rather than infer it from device
size: logical-map entries scanned while building victim scores, segment entries
examined during victim selection, and logical-map entries scanned during victim
relocation. Preserve the existing no-headroom skip counter alongside them so
reserve pressure is visible. These counters are diagnostics only and must never
influence selection. Existing `segment_mapped_pages` remains the authoritative O(1)
post-evacuation deadness check.

The private owned-RAM GC oracle may measure each successful foreground WRITE
with `CLOCK_MONOTONIC`, report one p99 per pressure round and retain exact final
image verification. Kernel GC wall and userspace WRITE wall are separate
clocks/contexts; their ratio is attribution evidence, not a CPU utilization
metric. A future background worker or reverse index requires a separate change
after this evidence demonstrates a material latency/scaling problem.

### Opposite-end asynchronous preparation

The ordered worker owns FIFO execution and may atomically reserve an unclaimed
preparation entry from the head. The asynchronous producer is pure preparation:
it never publishes mappings, submits lower I/O, changes ordering, or completes
upper BIOs.

When lower WRITE I/O is active, the producer prepares from the head because the
ordered worker is blocked in device service and cannot steal from
`preparation_incoming`. Lower READ service is deliberately not a producer wake
or head-claim signal: the qualified mixed-I/O evidence showed that rapidly
preparing the small interleaved WRITE queue can outrun accepted-work
replenishment and fragment retained windows. Outside active lower WRITE I/O,
tail preparation is credit-limited: each ordered inline WRITE may leave at most
one unconsumed tail token. The token is earned only after the ordered worker
atomically reserves its own FIFO head.

For a retained window, an earned `preparation_tail_credit` may survive the end
of that individual `swapz_process()` call. This bridges the admission gap
between companion BIOs without exposing worker-owned `batch_count` to
`->map`. Outside lower WRITE wait, the producer must not consume a token when
`preparation_incoming` is singular: on a one-entry list the nominal tail is
also the FIFO head, so claiming it forces an avoidable ordered completion wait.
The sole head and its token remain intact until a true tail exists behind it.
The producer itself is the tail-eligibility authority. Do not suppress a
credit-driven wake merely because the protected list is singular at the wake
site: owner qualification showed that this timing optimization reduced useful
throughput and worsened retained-window request/deadline geometry even though
the producer still rejected the lone head safely. A queued work item may overlap
a companion admission before it runs, and workqueue coalescing is part of the
measured schedule. If ordered inline work earns a fresh token while the producer
is already running, the producer may continue for that new token; it must stop
when no eligible credited tail remains. A nonempty window close clears any
unused token.

A cold lone head has no token and therefore does not wake the producer.
`->map` may wake parallel preparation for active lower WRITE service or for an
already-earned atomic tail credit. Lower READ service must not switch the
producer to head-first claiming. The legacy
`prep_lower_read_overlap_starts`/`prep_lower_read_overlap_ns` status tokens stay
present and fixed at zero so `make test` report parsing remains stable across
qualified sources. Wake decisions must not pre-screen a credit using
instantaneous preparation-list topology, read worker-private `batch_count`, or
depend on the instantaneous `ordered_worker_busy` interval. The producer
rechecks list shape under the same `queue_lock` before consuming the token.
READ/barrier execution may still grant one bounded tail token while it owns
ordered service time.

The ordered Device Mapper worker and LZ4 preparation worker both use
serialized `WQ_MEM_RECLAIM | WQ_UNBOUND` workqueues. The CPU-local preparation
experiment increased measured lower-I/O/LZ4 overlap but regressed useful mixed
throughput, lower-WRITE request geometry and worker-empty deadlines, so bound
placement is rejected and must not remain as production state. The single
preparation `work_struct` remains non-reentrant system-wide; scheduling
placement never changes FIFO, publication, completion or lower-I/O ownership.

Performance attribution belongs in kernel C at phase boundaries. Explicit RAM
copies are timed and byte-counted separately from LZ4. Engine write/read
processing also records wall time with synchronous lower-I/O wait subtracted.
Do not infer copy/CRC/packing cost from userspace elapsed time, and do not add
overlapping wall counters together.

PACK_READY closure is worker-tail owned. `swapz_accept_write()` may record
finite pack geometry in `single_pack_deferred` and
`accepted_burst_pack_ready`, but it must not flush a PACK_READY window.
The serialized worker closes burst-target, sampled-tail and service-proven-dry
windows only after refreshing its local and incoming accepted FIFO state. At the
initial four-record learned burst floor, only the selective two-record 4KiB or
three-record 8KiB geometry may establish a first pack; that first pack still
waits for a second accepted pack or an explicit sampled tail. Do not treat four
non-RAW compressed records fitting the existing 16KiB class as first-pack
evidence: `SWAPZ_MAX_COMPRESSED` makes that predicate effectively
tautological, so it closes at count four below the `count > 4U` K=1
asynchronous-detachment threshold. This restriction changes neither SWZ extent
classes nor the authoritative retention deadline.

If a ready window was held back only because the immutable K=1 lower WRITE was
still pending, the completion wake must finalize that run and deliver its upper
BIO completions before consuming the next accepted FIFO. A pending post-PACK
sample survives every interim worker pass while K=1 is in flight and is consumed
exactly once after that run is finalized. The completed-width evidence for a
PACK_READY close is the count from that one just-completed generation, not an
accumulation of earlier PACK_READY generations whose upper BIOs have already
been completed and may have resubmitted. Non-PACK split pieces may still
accumulate until a packed boundary because their preceding accepted generation
has not yet been released as a completed PACK_READY run.

After K=1 completion, bounded sampling counts both records already staged in
`batch[]` and plain retained-WRITE followers still queued in worker-local or
`incoming` state. Only the staged `batch[]` prefix may raise the learned burst
width: it was admitted before the completed K=1 generation released its upper
BIOs and is therefore disjoint closed-loop evidence. `local`/`incoming` entries
remain valid finite tail-close evidence, but they must not be added to the
completed generation for learning because they can already include immediate
resubmissions from those just-completed writers. A staged-only prefix does not
install a sampled-tail close target; however, the sample itself is no longer
left pending and therefore cannot suppress an otherwise valid service-dry or
learned-target PACK_READY close until the absolute deadline. Queued accepted
followers establish the finite sampled-tail target after they are consumed. This keeps the existing absolute deadline and adds no grace wait,
device-latency heuristic, K>1 slot or timeout scaling.

Retained bulk windows may contain incompressible RAW records before later
compressed records in admission order, while the flush planner already orders
the compressed prefix before the RAW tail. Early first/second-pack recognition
therefore evaluates the valid compressed records in the bounded admitted prefix
instead of allowing an earlier RAW slot to poison all later pack geometry. The
newest admission must itself be compressed, the exact compressed-record target
must be present, every compressed payload must remain valid and bounded, and
the existing 1/2/4-block extent limits and read-budget gates still apply. A
total `batch_count == 4` remains ineligible as a first pack even when RAW
records are skipped, preserving the settled rule that first-pack recognition
must not close below the `count > 4U` K=1 detach threshold. Geometry scans are
bounded by the tiny compressed target: return as soon as compressed count
exceeds the target or the target extent byte cap is already impossible, and do
not re-scan every total-count prefix to recover the earlier two-record check.
RAW records remain complete 4KiB records and are never treated as compressed
members of a pack.

For a complete single-bvec 4KiB WRITE, the still-owned BIO page may be mapped
with `kmap_local_page()` and used directly as the synchronous LZ4/zero-scan
input. The mapping must be released before the BIO can be completed or ownership
can change. Multi-bvec BIOs retain the copy fallback. An incompressible page in
retained bulk mode must be copied directly from the temporary mapping into its
durable `batch_bytes` slot exactly once before unmapping; do not bounce it
through `input_page`. In non-bulk RAW mode, BIO ownership survives the older
window flush, so release the temporary mapping and let `swapz_raw_write()`
perform its existing one copy afterwards. Direct mapping changes neither
publication nor lower-I/O semantics.

Engine write attribution separates planner, pack and publish phases. Pack
includes SWZ begin/append/seal work, including payload memcpy and first CRC.
Publish includes batch resume plus authoritative finish/revalidation after lower
completion. These diagnostics must not be used to skip CRC, generation or
transaction-snapshot validation without a separately qualified replacement.

The producer uses one constructor-allocated, zeroed 64-element prepared-page
array and an `atomic64_t` free mask, initialized with all bits set. Each element
is aligned and size-rounded to 64 bytes so adjacent producer/consumer slots
cannot share a boundary cache line. A `READ_ONCE(preparation_queued)` hint may
avoid an empty wakeup's reservation; the list must still be rechecked under
`queue_lock`, never inspected through an unlocked `list_empty()`. Claim a bit
using the shared production helper before taking `queue_lock` or claiming a
BIO. There is one serialized claimant; other owners only return slots, so at
most 64 concurrent returns can invalidate a compare/exchange and 65 attempts
bound the claim. An empty mask or exhausted retry budget leaves the descriptor
available for ordered inline work. No per-page allocation, semaphore wait or
second reserve is permitted.

An empty preparation queue, rejected tail claim or copy error must return the
reserved bit exactly once. A completed buffer belongs to the ordered consumer;
clear its BIO pointer before releasing the slot, before `bio_endio()` can
invalidate per-BIO data. Slot return uses a full barrier before relaxed
`atomic64_or`; a successful fully ordered claim acquires that release before
overwriting the array element. Returning the bit without this ordering is not
sufficient. Close admission before draining, and drain the producer again after
the ordered workqueue has finished: ordered callbacks may queue a late producer
invocation after the first producer drain. Check the all-free mask only after
this final drain. Destruction frees the array after both workqueues. Tail
claiming never consumes
completion/publication ownership: the FIFO worker can continue inline-stealing
unclaimed heads and releases prepared slots as it reaches completed tail
entries. Separate LZ4 scratch/work memory remains mandatory for concurrent
compression.

### Idempotent metadata-cache invalidation

`read_metadata_lru_clock == 0` is the canonical empty metadata-LRU state.
A mutation fence must always invalidate the one-entry read cache, but it may
skip clearing the 512-slot metadata validity array when the clock already
proves a previous invalidation emptied it. The first invalidation after any
metadata insertion must still clear all valid slots and reset the clock.

This optimization does not weaken physical-reuse safety or make cached
metadata survive a write, discard, GC mutation or barrier. It only makes
back-to-back invalidation calls idempotent in cost as well as semantics.
Range invalidation (`swapz_engine_invalidate_read_range`) must similarly return
before computing segment bitmasks when both extent-LRU and metadata-LRU clocks
are already zero.
Extent-LRU lookups (`swapz_read_extent_lru_lookup`) must likewise check
`read_extent_lru_clock` and `read_extent_segment_mask` before scanning the
16-entry residency array.

Greedy window ordering (`swapz_order_window_greedy` and `swapz_gc_sort`)
clears only the active batch/GC count of tracking bytes and advances a
`first_unused` lower bound across iterations while tracking `min_length`
across candidate partners other than `largest`, preserving the exact stable
largest-plus-best-fit pairing while skipping unreachable partner scans.
Bounded DP planning (`swapz_engine_plan_bounded_policy`) skips redundant
forward tie-break reconstruction when the backward-selected extent class does
not cross a segment boundary (`(alignment_cursor % SWAPZ_SEGMENT_BLOCKS) +
chosen_class <= SWAPZ_SEGMENT_BLOCKS`).
When a 1-block or 2-block extent at `index` already fits all remaining records
in the window (`take == count - index`), larger extent classes at that position
are strictly byte-dominated and skipped. `swapz_fit_count()` also uses a direct
one-block fast path (`*read_blocks = included`) when `blocks == 1U`, rejects
`blocks > 1U` immediately when `max_read_blocks == 1U`, and uses a dedicated
two-block fast path (`1U + (payload_start > SWAPZ_BLOCK_BYTES)`) with
single-subtraction `remaining` capacity tracking across multi-block classes.
`swapz_engine_plan_bounded_policy()` pre-checks batch-wide page validity and
uniqueness once when `logical_pages_unique == 0` so pre-validated or
duplicate-free windows skip repeated inner scans, and skips larger extent
classes whose `take` equals the immediately smaller class.
`swapz_engine_prepare_batched_run()` resets scalar run header fields without
clearing the 64-entry per-extent arrays that are populated up to `extent_count`,
and `swapz_engine_write_window_batched_read_cap()` skips the pre-validation
raw-page scan on normal multi-page bulk runs while initializing only `run.bytes`
and `run.txs`.
In `swapz_try_concurrent_read_slots()`, missing-range eligibility is checked
against shared cache metadata (`swapz_engine_required_read_range_cached`)
before priming private slot scratch (`swapz_engine_prime_read_slot`) so
rejected `<2`-slot read prefixes perform no scratch copies.
Singular worker-local queues (`list_is_singular(local)`) return immediately
before slot preparation, and `swapz_merge_read_slot()` clears private slot
`read_cache_valid` residency after absorption so subsequent write range
invalidations skip overlap checks on idle read slots.
Passive metadata-cache probes in `swapz_engine_prime_read_slot()` and
`swapz_engine_required_read_range_cached()` check `read_metadata_segment_mask`
before probing set tags, and `swapz_read_extent_lru_commit()` reuses the
already-resolved `extent_lru_slot` from `swapz_engine_read_page()`.
`swapz_read_extent_lru_lookup()` also rejects 1-block extents in O(1) because
`read_extent_cache` stores only multi-block (`extent_blocks > 1`) extents.
Adjacent read batching (`swapz_try_parallel_read_batch` and
`swapz_adjacent_extent_chain_candidate`) inspects mapped extents directly
via `swapz_parallel_read_extent_mapped` on the admitted prefix, avoiding
duplicate dependency scans on already verified BIOs, and filters candidate
extents to the FIFO head's segment and `SWAPZ_READ_COALESCE_MAX_BLOCKS`
neighborhood before sorting.


### Nonblocking preparation-slot reservation

The asynchronous producer must reserve one bounded prepared-page slot before
claiming any BIO from `preparation_incoming`. Reservation is nonblocking:
`down_trylock()` runs before `queue_lock`, and failure returns without
removing any entry. This is required once producer claims may proceed from the
tail; blocking after claiming an earlier FIFO entry could otherwise strand the
ordered consumer behind later prepared entries that own every slot.

If the producer reserves a slot but finds no eligible entry (including a lone
idle head reserved for inline steal), it must release the slot before
returning. Once an entry is claimed, exactly one slot is either transferred to
its prepared page and later released by the ordered consumer, or released on
producer failure. Queue ownership, BIO completion and map publication remain
unchanged.


Do not expose scheduler-accounted per-callback CPU as a portable module
metric. The rejected task-cputime experiment undercounted short nonblocking
preparation callbacks on the qualification host. Exact hot-path attribution
uses explicit monotonic phase timers around LZ4, CRC, copies, planning, packing
and publication. Whole callback entry/exit timing may be reported only as wall
residency and must be labeled as such: ordered residency includes synchronous
lower-I/O sleep and either callback can include scheduler delay. Diagnostic
timing must never participate in ordering, timeout or scheduling policy.
For asynchronous lower WRITEs, `pipeline_post_lower_wall_ns` may measure the
interval from the recorded lower callback timestamp through ordered
publication/release of the immutable run slot. It is attribution only and must
not become a runtime branch, timeout, admission gate or publication shortcut.

A precomputed payload CRC may cross from preparation into serialized packing
only when it covers exactly the immutable compressed payload and length being
copied. It can remove the pack-side source rescan, but publication must still
verify the payload CRC over the final `bulk_scratch` bytes. Likewise,
`swapz_finish()` may validate immutable extent metadata once and decode
subsequent descriptors without repeating that global validation, but every
record still requires final payload CRC, generation, liveness and transaction
checks before any mapping is published.


### Codec input validation before payload inspection

Public codec append entry points must reject null/zero/oversized payload
descriptions before hashing or copying caller memory. In particular,
`swapz_append()` must validate `length <= SWAPZ_MAX_COMPRESSED` before
calling the payload CRC helper; an invalid length is not permission to read
that many bytes from the caller. The prehashed append path retains the same
authoritative mutation-time validation. Sanitizer qualification plus a
source-order contract pins this fail-before-read rule. Descriptors and headers
must avoid redundant stack buffer copies on hot lookup/verification paths:
extent record counts are read directly at offset without header copies,
duplicate logical slot scans inspect 32-bit little-endian slots in-place
without stack array allocation, and record decoding constructs the decoded
view in a single store.


### Immutable lower-write run ownership

Batched lower-write packing must have an explicit ownership boundary before
asynchronous Device Mapper I/O is enabled. A `swapz_io_run` owns the exact
packed bytes, immutable staged transaction snapshots, per-extent offsets/takes,
raw/compressed identity and physical run geometry from the final
`swapz_batch_pause()` through definitive lower completion and authority
replay.

The portable engine separates `swapz_engine_prepare_batched_run()` from
`swapz_engine_complete_batched_run()`. Preparation may reserve and pack a
bounded prefix but must publish no mapping and submit no lower I/O.
Completion may replay/publish only after the caller supplies a definitive
completion result; failed, short or uncertain I/O quarantines every remaining
reservation. The existing synchronous writer is implemented on top of this same
split so the asynchronous path cannot grow a second publication state machine.

Upper BIO references, completions, PREFLUSH/FUA state and Linux callback
lifetime remain Device-Mapper-target ownership; the portable engine must not
depend on `struct bio`. A future async target may reuse a run buffer only after
its lower completion has been finalized and every paused transaction has been
published or aborted.


### K=1 ping-pong write pipeline

READs and barriers never grant idle preparation tail credit. A detached K=1
PACK_READY close must not consume an empty tail sample while its lower WRITE is
still incomplete; keep that sample pending until ordered finalization. A window
that recorded a read bypass is not eligible for asynchronous K=1 detach. This
guard is production-fixed after the two-host allow-after-read A/B showed no
service benefit; do not add a runtime override without new workload evidence.
`pipeline_read_bypass_skips` remains passive pressure attribution: increment it
only when every other detach predicate is satisfied and the fixed read-bypass
guard alone rejects the window. It must not alter timers, scheduling, authority
or completion ownership.

K=1 lower-WRITE detachment uses the last owner-qualified depth/backlog gate
from before ID80. A prepared window may detach asynchronously when it contains
more than four records or when a separate unclaimed preparation descriptor is
already queued:
`count > 4U || READ_ONCE(ctx->preparation_queued) > 0U`. Shallow windows with
no confirmed prepared WRITE successor stay synchronous. ID80's unconditional
`count > 4U` restriction was owner-refuted, while the later `count > 1U`
replacement was not a rollback and failed the loaded correctness gate before
benchmarking; neither policy remains in production. IDLE and DEADLINE retain
the pre-ID80 eligibility semantics. Do not add another shallow-count threshold
without a separately reviewed ownership model and owner-loaded evidence.

Idle asynchronous preparation must be self-gating. With no lower WRITE active,
a tail-credit workqueue wake requires at least four unclaimed preparation
descriptors. The initial accepted-wave starter observes the ordered head as
well, so it requires five descriptors total; after the head is stolen inline,
QD4 has only three tails and must remain entirely inline. The producer itself
must not consume an idle tail credit with fewer than two queued descriptors.
When a lower WRITE is actually active, any nonempty preparation queue remains
eligible for immediate head-first overlap. These gates add no timer, wait,
status token or mapping/publication owner.

`async_prepare` defaults on after matched owner evidence showed sustained fast
QD8/QD32 gains and QD4 neutrality. Loading with `async_prepare=0` retains the
synchronous qualification control. This policy change does not alter K=1 or
the existing depth/backlog activation gates. A complete multi-record non-FUA
window may be packed into the immutable `bulk_scratch`/`bulk_txs` run and
submitted with an asynchronous dm-io completion callback. The callback owns no mapping or
upper BIO completion: it records the definitive lower result, ends the lower
overlap interval, and wakes the single ordered worker. Only that worker calls
`swapz_engine_complete_batched_run()` and completes the original upper BIOs.

Once the full window has been copied into the sealed run, `batch_bytes` is
immediately reusable as the active collector. New WRITEs may therefore perform
zero/LZ4/payload-CRC preparation while the previous lower WRITE is in flight
without copying its packed run. A later close, read/barrier, zero/raw authority
mutation, GC retry or shutdown must finalize the prior run before staging or
mutating authority.

This first candidate keeps exactly one lower WRITE run outstanding. FUA and
hard control windows stay synchronous. If physical geometry yields only a
bounded prefix rather than the whole logical window, that prefix is completed
synchronously and the existing committed-prefix/GC retry path handles the
remainder. The experiment must never fragment a full packable window solely to
manufacture overlap.

Presuspend closes admission before waiting for an external lower completion,
then wakes/drains the ordered worker so every paused transaction is published
or aborted before teardown. While admission is closed during suspend/drain,
incoming requests are requeued with `DM_MAPIO_REQUEUE` (or killed with
`DM_MAPIO_KILL` if the target is failed). To prevent synchronous upper-layer
writers from waking up and submitting subsequent writes before DM core finishes
presuspend and sets `DMF_BLOCK_IO_FOR_SUSPEND`, completions processed while
drain is active are buffered onto `drain_completed_bios`. After draining queues
and issuing the physical flush, `swapz_drain` schedules `drain_endio_work` when
`drain_completed_bios` is non-empty to release buffered completions after
a bounded grace interval (25–35ms) ensuring presuspend returns to DM core and
DM core completes its SRCU grace-period barrier (`synchronize_srcu(&md->io_barrier)`)
to set `DMF_BLOCK_IO_FOR_SUSPEND`, and `swapz_free()` drains any
remaining buffered completions while preserving each BIO's recorded status,
ensuring subsequent requests are deferred by DM core rather than hitting closed
admission. The target drain invariant includes the asynchronous run-active bit
in addition to batch and authority state.


### Work-conserving opportunistic representation

A fast-media scheduling experiment may treat compression as speculative
preparation rather than a mandatory gate to lower submission. The lower path is
work-conserving only when accepted independent WRITE work exists, no ordering or
capacity fence prevents progress, and the target does not leave its lower-WRITE
service idle solely because an optional LZ4/delta64 result is unfinished.

The existing SWZ representation is sufficient: a batched immutable run may
contain a compressed prefix followed by whole-page RAW 4KiB extents. The
current planner already orders RAW pages after compressed records and publishes
both through the same paused-transaction completion path. An opportunistic
candidate must not add an on-disk type, extent class, alternate authority state
machine or separate completion owner.

The preferred implementation separates three bounded roles. Admission appends a
small descriptor containing sequence/order metadata and a safely owned reference
to the still-live upper data; it must not copy 4KiB merely to enqueue. One or
more independently measured preparation workers may claim descriptors and write
compressed bytes into preallocated reservoir slots. The ordered dispatcher owns
run formation, physical staging, authority reservation, lower submission and
upper completion. The descriptor queue and prepared reservoir must have fixed
memory bounds and no hot-path dynamic allocation.

A descriptor needs an explicit one-way state machine such as QUEUED ->
PREPARING -> READY_COMPRESSED or RAW_SELECTED -> SEALED -> COMMITTED/ABORTED.
A producer publishes READY_COMPRESSED only after its payload, length, encoding
and CRC are complete. READY observation must use acquire ordering; a relaxed
state load is insufficient on weakly ordered CPUs. If the dispatcher atomically
selects RAW first, a late producer result is discarded and its reservoir slot
is recycled; it must never republish or replace that generation. The dispatcher
never waits for a PREPARING descriptor solely to improve representation quality.

Queueing a preparation worker is not an ownership transfer. An unclaimed FIFO
head remains ordered-dispatcher owned until a producer has actually removed its
preparation descriptor under queue_lock. The dispatcher must not return merely
because producer work was requested. It may defer a PREPARING head only after
producer ownership is established and the stable RAW snapshot has been
published, so producer READY or lower completion provides a concrete wake edge.

Representation selection is terminal for that accepted generation. If a
compressed result is ready when the ordered owner seals the run, it may be used.
If preparation is not ready and lower service would otherwise go idle, the
ordered owner may select RAW after making an immutable 4KiB staging copy.
Once RAW has been selected for that generation, a later compression result is
discarded and may never replace or republish the committed RAW generation.
Zero elision is likewise optional optimization: a page dispatched RAW before
zero detection completes remains a correct RAW page.

A queue descriptor may retain a BIO/page reference to avoid an admission copy,
but a bare RAM address is never sufficient ownership: upper pages may be reused
after completion. Any direct page/bvec reference must remain pinned by the
upper BIO or by an explicit independently owned page reference until both the
dispatcher and every producer have dropped it. This lifetime rule determines
whether RAW can be copied directly at seal time or whether an independent
preallocated input snapshot is required.

A producer-owned BIO cannot be completed while a preparation worker can still
dereference its per-BIO state. A candidate that selects RAW while compression
is in flight must therefore either (a) keep the upper BIO and its per-BIO data
alive until the producer drops its reference, or (b) move preparation onto an
independently owned preallocated job/snapshot before allowing upper completion.
No cancellation design may create a second BIO completion owner, reuse a
preparation slot before its last reader exits, or make suspend/drain depend on
an unbounded worker cancellation.

The prepared-data reservoir is a cache of optional work, not an authority
queue. Its size may be larger than one write window so compressors can run ahead,
but it must remain bounded and pressure-tested. A larger reservoir is useful
only when READY_COMPRESSED occupancy is repeatedly consumed by the dispatcher;
large memory that merely accumulates stale or superseded results is rejected.
Compression workers should run while accepted backlog exists and CPU service is
available, especially while lower I/O is in flight. They must not preempt the
dispatcher enough to create lower-device idle gaps.

Do not make RAW fallback unconditional. A lone QD1 write may still be prepared
inline when there is no accepted backlog to overlap, because otherwise every
closed-loop slow-media write would become RAW. The work-conserving trigger is
service pressure: accepted work exists, the lower write slot is idle, and no
sealed/ready compressed run can be dispatched immediately. Under physical
capacity/reserve pressure, RAW may also be disallowed when its larger one-block
representation cannot be safely staged; capacity correctness takes precedence
over device utilization.

More run buffers are not a substitute for this rule. Additional immutable
lower-WRITE slots are justified only after a work-conserving K=1 implementation
shows nonzero ready-run wait: a complete next run repeatedly exists while the
sole lower-WRITE slot is still busy. Until then, increase representation
readiness and remove idle gaps rather than increasing K.

Mandatory attribution for this experiment includes: accepted-work/no-lower-I/O
idle wall, compressed-ready-at-dispatch pages, RAW-selected-because-not-ready
pages, ordinary incompressible RAW pages, preparation results discarded after
RAW selection, lower-WRITE active fraction, ready-run wait, lower bytes/requests
and useful throughput/p99. These counters are observational and may not alter
selection.


### Paused-run read independence

A paused immutable lower-WRITE group must not globally fence unrelated READs.
While the K=1 run is active, committed mappings remain authoritative until the
ordered worker replays and publishes the paused transactions. A READ may bypass
the active collector only when its logical page is absent from both the
collector and every transaction in the immutable run, authority replay is not
active, and no PREFLUSH/FUA/control fence applies. Malformed or mismatched run
metadata fails closed and forces ordered finalization. Same-page read-after-
write never bypasses the unpublished generation.

### Exact per-segment mapping counts

Production rotating-GC authority maintains one preallocated exact logical-map
count per physical segment. Every successful compressed/raw publication and
logical discard updates it in the same serialized authority phase as
`live_records`. Dead-segment selection and victim-role commit cross-check the
segment count against the sum of the segment's 256 physical live-record
refcounts; disagreement is corruption and fails closed. This sidecar replaces
production full-logical-map validation scans at dead-segment allocation and
post-evacuation role commit, while portable callers without the sidecar retain
the conservative full-map fallback. Victim discovery/evacuation may still scan
the logical map until a separately qualified reverse index exists.


### Timed benchmark telemetry ownership

Performance-policy counters used to explain measured mixed or write-only
throughput must be sampled at the same measure boundary as useful throughput and
independent lower-I/O deltas. Full-process status snapshots may remain private
session diagnostics, but prefill, warmup and post-measure activity must never be
reported as timed window, close-reason, deadline, burst-learning or preparation
evidence. Monotonic counters are differenced; policy state such as
`retained_burst_target` is an end-of-interval gauge and must not be subtracted.

### Explicit ordering-boundary state reset

Learned singleton fast-close state describes one uninterrupted admission stream.
FUA, PREFLUSH, DISCARD, shutdown and other explicit ordering boundaries clear
`singleton_deadline_streak` and `singleton_fast_close`, including empty
barrier flushes. Ordinary IDLE, DEADLINE and finite worker QUANTUM closes are
not ordering boundaries and must not erase the learned QD1 behavior they are
designed to preserve.

### Partial extent read residency

The serialized compressed-read cache may retain successfully fetched 4KiB
blocks from the current immutable extent in `read_scratch`. Residency is exact:
a block bit becomes valid only after its lower read succeeds, every authority-
changing write/GC/discard/barrier invalidates the mask, and generation,
descriptor and payload CRC validation still runs before returning a logical
page. This optimization may remove duplicate reads of sibling records but must
not turn cached bytes into mapping authority or weaken the existing mutation
fence.

### Bounded READ fan-out and coalescing ownership

The read-only `parallel_reads` parameter, default true, authorizes bounded
private-slot grouping and independent lower-READ fan-out across the
preallocated `SWAPZ_PARALLEL_READ_SLOTS` slots. `read_coalesce` is a
separate policy: it controls only exact zero-gap adjacent-range merging.
Disabling `read_coalesce` must not disable independent fan-out when
`parallel_reads=1`; the ID63 A/B must vary only the merge mechanism.

The ordered worker remains the sole mapping, retained-window, global-accounting
and upper-BIO ownership authority. For independent fan-out, it prepares private
slot engines, submits every missing lower range before joining any slot, then
waits for the bounded completions. The lower completion callback may only record
that slot's lower result and signal its completion object; it must never mutate
mapping authority, publish shared cache state or complete an upper BIO.

After join, each slot may complete its upper BIOs immediately after that slot's
own generation/descriptor/payload-CRC validation and copy succeeds. Completed
BIO pointers are cleared before processing the next slot, so a later slot
failure fails only BIOs still owned by the worker. Shared extent-cache state is
absorbed only for a successfully validated slot. Same-page and ordering
conflicts still fence through the serialized authority path.

ID63 adjacent coalescing runs before independent fan-out. It may combine only
requests already waiting in the admitted independent READ prefix, only when the
exact missing ranges form one same-segment zero-padding span within the bounded
scratch cap, and only when that coalesced chain covers the complete **bounded
fan-out batch** (up to the eight private distinct-extent slots, or reaching the
eight-block scratch cap). A smaller adjacent subset must fall through to the
asynchronous private-slot path rather than synchronously blocking unrelated
independent READs behind one merged request; a merged span retaining at least
two adjacent extents remains eligible when cache residency covers part of the
chain. A full eight-slot adjacent chain may execute while additional local READs remain
for the next bounded worker iteration. Its disabled arm returns before ID63 cache probes, adjacency scans
or coalescing counters; the subsequent independent fan-out path remains common
to both arms.

The master engine owns the 512-entry metadata LRU and 16-entry immutable
extent-residency cache. Private slot state is primed from master residency and
never publishes authority independently. Lower writes invalidate master and
private residency across the exact physical block range being overwritten
(`swapz_engine_invalidate_read_range`); full cache invalidation occurs on
REQ_OP_DISCARD, segment recycling, flush/FUA barriers, verify-after-write mode,
or when `invalidate_cache_on_write_admit` is enabled. The single-record
planned-write fallback follows the same rule: planning/staging failure must not
evict unrelated validated residency, and once the extent is sealed the engine
invalidates only `tx->start_block..blocks` immediately before lower mutation.
Verify-after-write remains the explicit full-invalidation exception because its
verification read reuses engine scratch. Post-`PACK_READY` tail
sampling and early window closure wait until detached in-flight K=1 lower writes
have completed to avoid premature single-tail deferrals and blocking stalls.
Independent READs may skip uncommitted plain retained WRITEs across the admitted
FIFO prefix, crediting read-bypass service evidence to the window those writes
subsequently form. Teardown drains the ordered worker after all submitted slot
completions have been joined. Useful READ throughput, p99 and independently
measured lower bytes/requests are all required evidence.

### Incremental GC victim accounting

Victim-selection cost metadata is per physical 1MiB segment, never per logical
4KiB page. The serialized authority updates mapped-page count, live-byte cost,
conservative I/O cost and proven minimum-live-block cost in the same fail-closed
publication/discard transition. Score arithmetic is prevalidated before mapping
mutation. `swapz_gc_choose_victim()` may scan segments but must not rescan
`logical_pages`. ID61b supplies a caller-owned volatile per-segment intrusive
logical-page list for relocation ownership: list unlink/append is O(1) in the
same serialized publication/discard transition, list traversal is bounded by
the exact mapped-page count, and any local link/map disagreement fails closed.
The list is never serialized into SWZ and research callers may omit it and use
the legacy full-map fallback.


### Physical placement and reclaim evidence

The historical aligned 4/8/16KiB placement policy could advance an extent
start to its own size. Canonical packed placement must not do that. Placement
telemetry keeps aggregate waste for continuity and separately counts segment
tail waste so qualification can prove that no avoidable intra-segment gap was
introduced while still recognizing a real segment-edge remainder.
Preserve the current on-disk SWZ extent classes. ID69 packed placement is the
only production placement policy: existing 1/2/4-block extents are placed
back-to-back at 4KiB granularity within a segment, with only real segment-tail
waste permitted. Append-only authority users must skip a segment tail when a
packed extent would cross the boundary, while checking the exclusive reserve
limit before committing the cursor or charging tail-waste counters. Report
b0623ae0 qualified the promoted default on both
maintained RAM models, so no aligned-placement module parameter, authority
field, planner branch or A/B harness may be reintroduced without new owner
evidence. Keep aggregate-hole, segment-tail and hole-split telemetry as
fail-closed structural invariants. No placement change may introduce a new
serialized extent class.

When exact per-segment mapped-page counts are available, dead-segment probing
must reject a nonzero mapped segment before scanning its 256 physical block
entries. A zero-mapped reuse candidate still requires the complete
live-record/extent consistency scan before overwrite; optimization may leak
capacity on inconsistent positive counts but must never turn a false zero into
silent reuse.

Successful whole-segment DISCARD is remembered per segment so the same dead
bytes are not synchronously discarded twice before reuse. Any later lower
WRITE clears that successful-discard state before submission. When an upper
REQ_OP_DISCARD synchronously removes the final mapping from a closed segment,
the ordered worker may issue the whole-segment DISCARD immediately; later
allocator reuse must then hit the existing duplicate-suppression state.
Asynchronous early DISCARD remains a separate concurrency experiment and may
not race allocation or an upper BIO.

Per-segment program/open counters describe logical allocator write cycles only.
A default-off allocator experiment may use them to compare logical-open spread
or choose the least-opened eligible destination without additional I/O. They
are not NAND wear measurements; neither that experiment nor a GC score tie
break may be described as wear leveling or authorize cold-data relocation
without separately approved physical-media evidence.

### Delta64 SIMD backends

The delta64 classifier remains scalar and sampled. Architecture SIMD backends
must be byte-identical to scalar delta64 and may accelerate only the full-page
transform/inverse after classification. x86 dispatch is capability- and
xstate-gated; AVX-512 requires AVX-512F plus enabled SSE, YMM and AVX-512
xfeatures. Transform and inverse selection are independent: a wider forward
transform must not force a dependency-heavy inverse backend without same-host
batched evidence. Keep each SIMD implementation in its own translation unit
with explicit compiler flags so generic kernel C cannot acquire vector
instructions accidentally.

### Core-2-class cache locality

Optimize hot metadata lookup for a 32KiB private L1D and shared L2 without
assuming an LLC. The current directory has 128 aligned four-way sets and 512
block-zero storage slots. Alpha.27 assigns each key a primary and a distinct
secondary set, using a different high-bit-mixing hash for the latter. Lookup
must finish the primary set before inspecting the secondary; primary hits touch
at most one 64-byte tag line and every lookup inspects at most eight tags.
No global directory scan, victim relocation chain or new payload allocation
belongs on this path. Mutation fences advance the existing epoch.

Commit must search both candidate sets for an existing epoch/start/class key
before selecting an invalid way or the oldest of the eight candidates. An
invalid primary way cannot hide a matching secondary tag. Refresh an existing
key's age without copying 4KiB or charging replacement. One immutable extent
must occupy at most one slot across both choices. Counters distinguish primary
and secondary lookup hits; commit deduplication and passive residency probes
must not inflate those hit counts. Preserve generation/CRC validation and
block-zero payload copy avoidance. Qualification must compare actual lower
reads, useful throughput, tails, engine wall time and host CPU; more hits alone
do not establish an end-to-end win.

SSE2 delta64 keeps its full-page semantics byte-identical to scalar C but starts
vector work after the first 16 bytes so pair-sized output stores and inverse
loads/stores do not begin at byte offset 8. This targets older x86 split-access
costs without assuming a wider ISA or changing predictor policy.

## Validated-read and publication CPU fast paths

A metadata cache hit may skip full SWZ metadata validation only when the bytes
were published to that cache after a successful authoritative read and are not
still marked as provisional coalesced input. Descriptor-only lookup does not
weaken read validation: compare the cached on-media sequence with the observed
map before any payload lower read, then retain the existing logical-page,
generation, payload bounds/encoding, authority and payload-CRC checks. Cold
metadata and unvalidated coalesced seed bytes always use the full validator.
When a validated extent-LRU block replaces provisional scratch, clear the
corresponding provisional bit. Cache refresh and slot priming copy only blocks
that are not already resident.

The generic bounded planner must remain defensive against duplicate logical
pages. A private caller may bypass the inner duplicate search only immediately
after one complete bounded-batch uniqueness validation and without allowing an
intervening mutation of the page list.

CPU-only hot-path shortcuts may reuse facts already proved in the same
serialized operation, but they must not remove a fail-closed boundary. In
`swapz_finish()`, an old authoritative map may feed GC byte/I/O/min-block cost
directly only after its physical range, extent class, segment and sidecar
preconditions have already been checked; bounded extent/segment delta lookups
may search newest-to-oldest without changing append or apply order. READ
eligibility may reject non-READ, barrier, unmapped and RAW BIOs from the O(1)
authoritative map before the more expensive collected/in-flight dependency
scan, but every mapped candidate must still run that dependency scan before
fan-out. Metadata set lookup may cache the immutable epoch/tag base in locals
for one probe. `swapz_validate()` may rely on the monotonically decreasing
packed-payload end relation only while offsets/lengths remain 16-bit decoded
values, positive length and maximum compressed-length checks remain intact,
and exact adjacency to `previous_end` is still required.

Publication may authenticate an immutable SWZ extent's header and descriptor
bytes once with `swapz_validate_metadata_crc()`, then fold descriptor
adjacency and transaction identity into the existing `swapz_finish()` Phase 1
walk. Public `swapz_validate()` remains the complete standalone validator and
must retain duplicate-logical detection. Publication may omit that quadratic
duplicate scan only because every decoded logical/generation pair is compared
positionally with the already-authenticated, duplicate-free transaction.

The batched engine may reuse its one window-wide uniqueness proof through
`swapz_stage_batch_unique()` and the unique prehashed codec append. The stage
fast path skips only the repeated duplicate search: logical range and generation
overflow checks remain active before map access. The codec fast path skips only
the builder's prior-record logical scan; payload pointer/length, encoding,
generation, builder capacity and serialization checks remain unchanged.

After `swapz_batch_resume()` verifies the paused transaction CRC, sequence,
range and current generations and copies the active prefix into
`authority->active_tx`, completion may pass that authority-owned pointer to
finish/abort identity checks. `swapz_is_active()` may self-accept only that
exact pointer after all scalar active fields, class and count checks succeed.
Every external caller-owned transaction pointer must still compare every active
record against the immutable authority snapshot.

`swapz_finish()` publication preflight is serialized and uses only
authority-owned, fixed-size scratch. Aggregate old-extent reference removals,
per-segment mapped removals and GC score deltas without mutating global
accounting. Validate all aggregate underflow/overflow conditions before
publication, then apply each aggregate once and publish distinct mappings.
Never move a fallible check into the mutation phase. Keep these summaries out
of the kernel stack; `SWAPZ_MAX_RECORDS` bounds all scratch.

Paused transaction integrity hashes only the active prefix:
`offsetof(struct swapz_tx, records) + count * sizeof(records[0])`.
`swapz_stage*` must continue to zero-initialize the transaction before filling
active fields. The hash must always cover start block, sequence, extent class,
count, and every active logical-page/generation record.

## LZ4, zero routing and delta64 microarchitecture

Ordinary first-pass LZ4 is fixed at acceleration one; the retired runtime
selector must not be reintroduced without a new matched loaded experiment.
Delta64's second LZ4 retains its separate read-only acceleration control because
it is an opt-in rescue path with independently measured economics.

The exact-zero scan is allowed only after ordinary LZ4 has produced the
existing tiny-candidate admission. If the full 4KiB source page is zero, route
it directly to zero elision before delta64 rescue, payload CRC or batch payload
copy. Any nonzero page follows the unchanged compression/CRC path.

SSE2 delta64 must consume one new aligned 16-byte source vector per 16-byte
output pair after the scalar 16-byte prefix. Retain the prior vector and use an
SSE2 shuffle for predecessor formation; inverse prefix formation must shift the
already-loaded delta register rather than reload a lane from memory. Inline
assembly is restricted to these explicit SSE2 register operations and the
native x86 qualification must verify the emitted instructions.

Production transform timing surrounds `swapz_predict_delta64()`, not just the
raw architecture function. On x86 this intentionally includes the per-call
kernel FPU enter/exit wrapper. Native backend timings remain raw implementation
evidence and must not be substituted for the wrapper-inclusive production
cost.

## Bounded read-chain and GC companion rules

ID63 active coalescing may combine 2..8 exact missing ranges from already-
admitted independent READs when they form one same-segment zero-padding span.
The hard cap remains eight blocks/32KiB. Passive full-extent chain counters are
conservative opportunity evidence; active savings are recorded separately as
N-1 requests for an N-extent successful chain.

A successful authoritative read exposes the payload CRC it just verified so GC
relocation can reuse that value for the unchanged payload bytes. Clear this
value before each read and on read-cache invalidation; never reuse a CRC from a
failed or stale read.

GC victim tie traversal and dead-segment allocation share the circular allocator
probe only as a fairness cursor. Successful rotation must not reset that cursor
to the victim index. This is logical allocator fairness and must not be
described as physical flash wear leveling.


### Predictor-first rescue and independent lower-READ fan-out

With delta64 rescue enabled, the sampled classifier runs before ordinary LZ4.
Score>=24 pages run delta64 plus the configured rescue LZ4 first. A candidate
at or below 2024 bytes may be adopted directly, with explicit
`delta64_direct_adopted` and `delta64_first_lz4_skipped` telemetry. Larger
candidates fall back to ordinary LZ4 and retain the existing strict comparison;
lower scores run ordinary LZ4 first and may enter only the packing-cliff route.
The telemetry counters maintain a strict mutually exclusive partition where
`delta64_raw_rescues + delta64_lz4_rescues + delta64_direct_adopted == delta64_adopted`;
direct adoption deliberately bypasses baseline LZ4 and must not increment `lz4_rescues`.

Independent compressed READs may fan out across the preallocated private read
slots. All missing lower ranges are submitted before the ordered worker joins
them. Completion callbacks only record lower completion; they never publish
shared cache state or complete upper BIOs. Shared cache absorption occurs only
after ordered-worker validation and successful upper completion.


### Capacity exhaustion and physical-backing invariants

`-ENOSPC` is a per-write capacity result, not an integrity failure. It must
not set `ctx->failed`; already-published mappings remain readable. If a READ
first drains an older window that exhausts capacity, the uncommitted writes
fail while the READ continues against committed authority.

Non-`null_blk` backing is disabled by default. When explicitly enabled it
requires a valid exact-size SWAPZ authorization header in reserved block 0.
All mapping data and segment discard ranges start after that reserved block.
Fault-injection knobs are forbidden on physical backing.


### Alpha.29 work-conserving dispatcher candidate

Alpha.29 keeps one unbound producer lane, K=1 and the existing 64 preparation
slots. A producer copies one stable 4KiB RAW snapshot before optional LZ4,
publishes `WRITE_ONCE(entry->prepared_page, prepared)`, and signals persistent
snapshot publication via `complete_all(&entry->preparation_snapshot_ready)`. The
`prepared_page` pointer must not become dispatchable before that snapshot is
complete: publishing it early without a snapshot-ready gate would allow the
dispatcher to select RAW while `raw_bytes` is still being filled. Lockless pointer
accesses use `READ_ONCE`/`WRITE_ONCE` to prevent compiler tearing, while cross-CPU
publication and memory ordering are provided by `complete_all(&entry->preparation_snapshot_ready)`
and `wait_for_completion(&entry->preparation_snapshot_ready)`. The ordered
dispatcher enforces snapshot wait (`wait_for_completion(&entry->preparation_snapshot_ready)`)
on every entry not stolen inline (`!entry->preparation_inline`), ensuring `complete_all`
provides a persistent, one-shot barrier across all scheduling passes and deferred
worker revisits without repeat-wait deadlocks. After `complete_all(&entry->preparation_snapshot_ready)`
is called, the background producer relinquishes the entry descriptor and never
dereferences `entry` or `entry->bio` again.

If the lower WRITE is still active, a PREPARING FIFO head is deferred after the
stable snapshot is published. Producer READY or lower completion wakes the
ordered dispatcher; if lower completion wins, PREPARING atomically becomes
RAW_SELECTED and a late compressed result is discarded. READY state observation
is acquire-ordered.

The ordered worker may force an unclaimed accepted WRITE to RAW only while the
lower WRITE path is actually idle, before the first eight-record pressure hand,
and only when the active batch plus unclaimed preparation queue already prove at
least eight records of accepted backlog. QD1/QD4 and later records in a larger
wave therefore retain their inline compression opportunity. Once K=1 is in
flight, remaining accepted work keeps its compression opportunity so
producer/ordered preparation can overlap lower service.

Eight records are the minimum pressure hand, not a maximum run size. The worker
refreshes accepted followers from incoming before evaluating local readiness.
A retained work-conserving hand may not split an already-accepted plain-WRITE
FIFO below the effective learned/sampled target merely because the next
representation is not READY. When the accepted FIFO is genuinely dry, an
undersized retained batch remains on the existing pinned retention deadline
unless a complete multi-pack hand of at least eight records is already staged.
Non-retained operation keeps the historical immediate work-conserving behavior.

Packed work-conserving closes below the effective target are attributed
explicitly to `SWAPZ_PACK_CLOSE_SERVICE_DRY`; BURST_TARGET is reserved for
actual learned/sampled target closure. No attribution decision changes the
mapping, completion or lower-I/O ownership rules.

Producer and consumer each hold one reference to a prepared slot. Only the final
drop returns the slot to the free mask, so an upper BIO may complete after RAW
selection while the producer finishes against slot-owned memory. Producer BIO
access must end before snapshot completion. The historical per-producer 4KiB
input scratch stays removed; producer fallback writes directly into the slot's
stable `raw_bytes` snapshot.

ID83 instrumentation includes work-conserving hand/dry closes, representation
selection, late-result discard, reservoir occupancy, K=1 ready wait, and
`accepted_work_lower_idle_events/ns`. For each existing retained open-batch
lower-idle interval, four monotonic counters partition that same wall time:
`accepted_work_lower_idle_undersized_batch_ns`,
`accepted_work_lower_idle_worker_unscheduled_ns`,
`accepted_work_lower_idle_preparing_head_ns`, and
`accepted_work_lower_idle_no_ready_work_ns`. Their interval deltas must sum
exactly to `accepted_work_lower_idle_ns`. The separate
`accepted_work_lower_idle_post_lower_ns` diagnostic measures callback-to-
publication hold after lower completion when accepted WRITE work is already
waiting; it is intentionally not part of that four-way conservation identity.
All idle attribution is observational and must never change scheduling policy.
