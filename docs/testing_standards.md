# Testing Standards

**Immutable naming policy (read before every prompt):** The project is `swapz`; the kernel module is `dm-swapz.ko` (loaded as `dm_swapz`); the Device Mapper target is exactly `swapz`; and the module alias is `dm-swapz`. Never put implementation-generation numbers in product, module, target, source-path, report, workflow, helper, or schema names. `SWZ3` is reserved for the on-disk format identity.

**Single official test command (read before every prompt):** Run `make test` at the repository root for every supported swapz test and benchmark. A complete run must report BLOCKED (nonzero) if safe noninteractive privileged qualification cannot run. Do not create, publish, recommend, or document alternative test commands. Private scripts and CI jobs are implementation details, not operator interfaces.

## Official interface

The root checkout has one supported testing interface:

~~~sh
make test
~~~

It must execute the supported qualification in order and fail closed. Rootless/CI-only success is partial evidence and cannot substitute for the loaded owned-RAM phase. The Device Mapper target is exactly `swapz`; the module alias is `dm-swapz`.

## Required stages

A complete run includes:

1. Product/module/userspace/helper build.
2. Direct production-C native tests plus source, build-interface, report and packaging contracts.
3. Kernel W=1 build.
4. Kernel W=2 build.
5. Owned RAM-backed `null_blk` correctness, lifecycle/fault checks, matched mixed benchmark evidence and bounded write-only QD evidence.

Stages are ordered and fail fast. Privileged device sessions must never overlap. If noninteractive privilege or safe owned-device provisioning is unavailable, the complete run reports BLOCKED rather than silently skipping loaded work.

## Direct production-C tests

Native tests compile the real `src/kernel/{codec,authority,engine}.c` where applicable. They cover codec integrity, authority publication, torn/short failure, overwrite generations, discard, zero-write representation, online packing, randomized authority, lower-run aggregation, flush/FUA accounting, retention/window policy and GC rotation/cost invariants.

Source contracts validate behavior that requires the Linux Device Mapper target itself, including BIO ownership, queue/drain ordering, null_blk-only admission, lower-I/O accounting and current report/build contracts. Source-string assertions are secondary to executable production-C coverage.

## Loaded correctness

Loaded tests use only newly created, positively owned, RAM-backed `null_blk`. Before and after use, verify device identity, size, major/minor, DM UUID, holders, mounts and active-swap aliases. Never substitute a physical or existing block device.

The deterministic lifecycle oracle must preserve exact readback, RAW fallback, zero elision and explicit flush behavior. The loaded qualification must also recreate a fresh target on the same positively identified RAM lower and force repeated live-GC evacuation under bounded capacity pressure. Passing GC evidence requires at least two nonzero victims/role rotations, nonzero GC lower READ and WRITE traffic, distinct victim/destination identities, and byte-exact verification of all 4096 logical pages after pressure. This proves loaded GC correctness/cost only on synthetic RAM; it is not physical-wear evidence.

Retained-window suspend/resume must drain accepted ownership and verify all pages. Synthetic pre-submission WRITE and FLUSH injection must fail closed. These synthetic failures are not evidence for torn/device-originated errors.

Cleanup never force-removes uncertain resources. If identity or teardown is ambiguous, quarantine and fail.

## Benchmark pairing and provenance

The mandatory mixed matrix uses two RAM-only latency models: 10 MiB/s with 1 ms completion and 80 MiB/s with 0.15 ms completion. The slow model remains a bounded four-session directional control (two sync, two async). The fast model runs ten sessions in the fixed sequence `0,1,1,0,0,1,1,0,0,1`, which forms five adjacent counterbalanced sync/async matched rounds. The control candidate inside every session is `off`; the product candidate is `swapz`.

Both arms of every session carry the same exact source SHA, fixture SHA-256 and trace SHA-256. Missing or divergent provenance is INCONCLUSIVE. Every logical workload must finish its byte-exact oracle before a performance verdict is considered. The five fast matched deltas use a two-sided Student-t 95% confidence interval with four degrees of freedom. Report both the paired mean and interval; do not replace paired analysis with an interval over unpaired arm means.

The write-only QD1/4/8/32 sweep keeps slow QDs and fast QD1/QD4/QD32 directional. Fast QD8 uses the ten-session confirmation sequence and reports paired 95% confidence intervals for useful throughput, lower requests and lower bytes. Fast QD4 previously received five matched rounds and returned to directional status after its CI crossed zero. A new promotion claim for QD1/QD4/QD32 requires its own >=5 matched rounds. Rootless Make-interface/source fixtures must assert the shared sequence and fast-QD8-only mode selection.

## Report contract

Official human-readable and JSON reports use `swapz`, not implementation-generation labels. Schema keys are version-neutral. SWZ3 is reserved for on-disk format discussion.

Reports distinguish useful logical throughput, backing WRITE throughput, lower READ/WRITE bytes and requests, p95/p99 where available, process CPU scope, kernel counters, GC, fixture/trace/source provenance, lifecycle result and cleanup. Never call synthetic RAM results physical SD/SSD evidence.

The console report is a compact operator summary. It keeps raw and synchronous
throughput controls because they isolate compression and asynchronous scheduling
effects, but suppresses repetitive per-control diagnostics. Detailed cache,
window and counter evidence remains in the single replace-in-place
root `test_results.json.xz` report.

The retained production counters must describe active decisions only. Closed/rejected diagnostic counters are removed from production and report schemas.

## Evidence levels

Source contracts show structure, not loaded semantics. Native C shows portable product logic, not Device Mapper runtime. W=1/W=2 shows compilation, not correctness. Owned RAM-backed loaded tests show real kernel BIO behavior on the test host, not physical-media benefit. Only separately authorized physical testing can establish behavior on a particular real device.

## Current qualified baseline

Source `1352e46f3051315eab273ae11c0a5a9bd54ce340` passed all five stages
and published the canonical report as
`e25f0a0d0e1c3b4ea65e7297593f5b10d4dffe27`.

Fast mixed async/sync is 23.12/22.63 MB/s with 977.6/883.2 lower WRITE
requests. Five matched pairs give +2.2%, CI [-3.2%,+7.7%], while absolute
request delta is +94.4 CI [+14.3,+174.5]. Fast QD8 is +23.1%,
CI [+8.4%,+37.9%]. Fast QD4 is +1.4%, CI [-0.7%,+3.6%], and returns to
directional status. Kread is inconclusive in this generation.

ID56 reports fast async post-PACK tail0/inflight 604.2 versus zero sync; tail1
and tail2+ while active are 116.4 and 70.4. The same condition also appears on
slow async without a throughput difference, so ID57 must be qualified as a
controlled scheduling intervention rather than assumed beneficial.

ID57 gates only early PACK_READY while K=1 lower completion is pending and
preserves only zero-tail pending evidence across active/finalization-only
passes. Timed telemetry must expose busy admission/worker deferrals, zero-tail
deferrals, completion-only holds, zero/one/many resolutions, aborts and
post-finalization closes. Rootless contracts must prove hard boundaries and
tail>=1 behavior remain outside the gate.

## Deferred optimization evidence gates

The following ideas stay in the maintained test plan even when they are not the
active experiment.

- **ID58 same-filled:** opportunity collection is offline from immutable fixture
  bytes and trace events. It must not add a production hot-path scan merely to
  measure prevalence. Zero pages are excluded because zero elision is already
  a separate qualified representation.
- **ID59 dedup:** trace evidence uses exact 4KiB byte equality, not hashes alone,
  to classify same-page rewrites and resident duplicate payloads. Synthetic
  fixture-pool reuse is not a production prevalence claim. An active dedup test
  later requires byte-exact collision verification and refcount/COW/GC/discard
  failure-path coverage.
  The compact console summary is emitted only from a successfully validated
  mixed-matrix verdict; write-saturation parsing must not depend on this
  opportunity record.
  Rootless public-Make fixtures must synthesize the same opportunity schema so
  the mocked loaded matrix cannot bypass or accidentally fail the report
  contract.
- **ID60 read coalescing:** first report the already-collected same-extent share
  of Kread pairs. New coalescing may operate only on reads already queued; no
  grace timer or future-arrival wait is allowed. Acceptance requires lower READ
  request reduction with no p99 regression and unchanged byte oracle.
- **ID63 adjacent distinct-extent READ coalescing:** the ID60 same-extent
  pair ratio does not answer whether physically contiguous *different* extents
  are queued together. Before any lower-I/O merger, collect passive opportunity
  counts from already-admitted independent READ prefixes: physical adjacency,
  immutable authority/generation, cache-resident blocks, actually required
  block spans, excess-read-byte risk and barriers. A later bounded opt-in must
  compare at least five matched sequential/random pairs against Kread=2 using
  identical trace/fixture/source, with byte-exact upper readback, per-record
  CRC verification, cache invalidation and GC/overwrite races, fault/short-I/O
  handling, fewer lower READ requests, no more lower READ bytes and no read-tail
  regression. Never delay service to await future BIOs.
- **ID29 dead-segment DISCARD/TRIM:** separately qualify RAM-only support,
  alignment, failure/unsupported fallbacks, exact whole-dead-segment ownership,
  ordering relative to rotation/reallocation and all lower traffic. No lower
  DISCARD submission may authorize reclaim of live or pending data. FTL wear
  benefit requires separate owner-approved physical-media evidence.
- **ID61 background GC:** before creating a worker, add an owned-RAM phase that
  measures foreground-GC stall/headroom during useful I/O. Qualification must
  include total GC lower READ/WRITE traffic, reserve safety, useful throughput,
  p95/p99 and exact final image.
- **ID38 K>1:** current evidence keeps it on hold. Reopening requires sustained
  ready-run pressure while K=1 is busy, lower queue headroom >1 on the target
  model, and a separate >=5-pair K=1/K=2 comparison. Never infer K>1 usefulness
  from raw device hwq depth alone.
- **ID62 real device:** current host-safety rules prohibit collection. Do not add
  a physical-device path, environment toggle or alternate public test command
  to bypass that gate.

## Open qualification gaps

The next architecture experiment is an immutable ping-pong WRITE pipeline:
while one sealed run is in lower I/O, a separate active collector may admit and
prepare new writes. Per-page LZ4/CRC must happen during collection, not after
freeze. A shared global accumulator/planner is retained; device parallelism is
expressed as a bounded number of immutable in-flight runs rather than per-lane
write accumulators.

Before asynchronous lower I/O can return from submission, every in-flight run
must own its packed bytes, staged transaction state, upper BIO references,
ordering/FUA state and completion result until lower completion and authority
publication. Same-page writes across runs require generation reservation or an
ordering fence. Completion remains fail-closed.

The first pipeline qualification uses one lower run outstanding plus one active
collector. Higher lower-I/O depth is a later explicit K experiment. Multiple
preparation workers/credits are tested only if the new collector actually shows
sustained eligible backlog.

Parallel READ service is separate: it requires private read scratch and must
dispatch immediately when lower I/O is idle. Reordering/coalescing is permitted
only for reads already waiting behind active lower work.

Genuine device-originated/partial lower errors, long-run resource pressure,
larger controlled cold-read working sets, >=5-pair statistics, deliberate CPU
oversubscription/low-RAM qualification, automatic device-queue-depth policy,
physical-device behavior and physical endurance remain open. Physical-device
admission remains separately blocked.


Source contracts should assert retained scheduling semantics rather than a
particular obsolete branch spelling: retained writes must reach the ordered
worker immediately, while retention-off ordinary writes retain zero-delay
single-instance queueing.


The canonical report is the single root file `test_results.json.xz`. The
runner keeps it unchanged while qualification is executing so loaded safety
checks still see a clean tested tree. At the end of every completed PASS, FAIL,
or BLOCKED run it atomically replaces that file with the sanitized stage,
failure-phase/diagnostic, lifecycle and benchmark result for the exact
`tested_commit_sha`.

After writing the file, `make test` automatically publishes only that report
to `main` using Git plumbing: origin/main must still equal the exact tested
commit, the push is nonforce, no branch or PR is created, and any unrelated
tracked/index change causes publication to be skipped. After a successful push
the local main ref/index advances to the same report-only commit, leaving the
checkout clean. Root-owned private session logs are implementation details and
must not be required for ordinary failure diagnosis once the sanitized report
has been published.


Rootless incremental-build fixtures mirror the current `src/` and `tests/` layout; they must not recreate removed top-level `tools/` or `userspace/` directories.


Native shell regressions source shared helpers only from `tests/tools/`.
Current reports, test output and product-facing diagnostics use `swapz`;
implementation-generation labels are not permitted outside explicit disk-format
history.


Native engine tests call the same batched write entry point as the product.
Tests that omit bulk callbacks thereby exercise its production sequential
fallback; no test-only write wrapper is part of the engine API.


The owned benchmark table validator must match the current Device Mapper
constructor exactly. Removed constructor fields are removed from replay parsing
in the same change; stale positional compatibility parsing is forbidden because
it can reinterpret ordinary options as fault injection and falsely BLOCK a
healthy product arm. Benchmark diagnostics and errors use the product name
`swapz`, never implementation-generation labels.


The retained suspend/resume oracle gates on observing an open retained window,
successful suspend/resume, a nonfailed target, and byte-exact verification of
all accepted pages. The bounded private writer starts first; the status sampler
then polls without an added sleep for exactly as long as that writer process
remains alive. A fixed poll-count loop is forbidden because it can exhaust
before the child is scheduled and falsely miss the first 4ms retention
opportunity. The sampler must still observe `retain_timer_arms > windows`;
historical timer activity is not a substitute for an actually open window. The
maximum supported 4ms deadline can legitimately expire between that observation
and the separate suspend request, so the oracle must not require a specific
close-reason counter afterwards. Loaded failure reporting skips the generic
cleanup epilogue so the preceding specific sanitized failure remains visible.


Production-C differential tests for the lower-run writer must not freeze an
old physical extent layout when the experiment intentionally changes planner
tie ordering. They still require identical useful payloads and generations,
byte-exact readback, no authority visibility before lower completion, zero
default padding, and no increase in lower WRITE bytes. Physical start blocks,
record indices and extent classes may differ when those changes are the
mechanism being qualified.


The same rule applies to mixed compressed/RAW windows: compressed planner
placement is not an ABI. Differential coverage must preserve RAW CRC/type
authority, logical generations, exact readback and equal lower bytes rather
than require identical physical starts or transaction sequence assignment.


Source contracts for retained suspend/resume follow the observable safety
contract and must not resurrect the removed close-reason race. They require an
observed open retained window, explicit suspend/resume, a nonfailed target and
the byte-exact lifecycle marker; they explicitly reject a mandatory
shutdown-close delta.


Rootless Make-interface fixtures must emit the same current lifecycle marker as
the loaded parser. Synthetic fixture text is not a compatibility surface; when
the report contract changes, stale fixture markers are updated rather than
keeping parser aliases for removed semantics.


The direct production-C zero-elision test includes an intentionally unaligned
4KiB input view. It must accept an all-zero page, reject a nonzero final byte,
and never depend on bytes outside the logical page, preserving the exact
predicate while allowing word-at-a-time implementation.


Source contracts for the ordered worker assert the active finite-quantum
semantics rather than one historical loop spelling. A bounded
`while (remaining && !list_empty(&local))` plus an explicit decrement is
equivalent evidence to the retired pre-decrement break idiom only when FIFO
requeue, the hard quantum, and cooperative rescheduling remain asserted.


Write-only QD qualification records window-size bins and pack-ready/deadline/
idle close deltas for every QD/mode pair, plus the final learned retained-burst
target. These are attribution only and cannot substitute for throughput, lower
bytes, latency or correctness acceptance.


Rootless Make-interface fixtures that synthesize the loaded write-only pilot
must include the same window-size, close-reason and retained-burst-target
attribution required from the real loaded reporter. Fixture success must not
bypass a newly required evidence field merely because no kernel device is
present.


Dry accepted-pack qualification keeps the existing write-only window attribution
and additionally requires direct production-C/source coverage that a complete
accepted pack may close on a proven dry queue below a larger learned target,
that admitted-tail evidence observes worker-local FIFO entries before later
`incoming` entries, and that a single two/three-record deadline cannot shrink
the learned target below the four-record floor. These are scheduling-policy
checks only; acceptance still depends on useful throughput, lower bytes and
requests, latency and loaded correctness.


Source-contract helpers that extract only a function body must assert only text
that can actually occur inside that body. Signature parameters belong to a
full-source/signature assertion, not to a body-only search. When a production
helper gains parameters, every call-site spelling asserted by source contracts
must be updated in the same test change; do not keep stale call syntax as a
compatibility alias.


Service-proven retained closure qualification must distinguish the write
admission decision from the worker-tail decision. Source coverage requires
admission to ignore the accepted-second-pack shortcut below the effective
target, while the worker-tail path may use it only after refreshed queue state,
no active sampled tail, and prior packed-chain or independent-read service
evidence. A successful independent read while a retained write window is open
must be boundedly attributed to that window and cleared when the nonempty
window commits.


Ordered-worker preparation-steal qualification must preserve the producer's
no-publication rule and the original completion wait for entries the producer
has already claimed. Source coverage requires the steal decision and list
removal under `queue_lock`, an explicit inline marker, distinct producer LZ4
work memory, no producer use of the ordered worker's work memory, and combined
reporting from separately written timing accumulators. Drain and teardown must
still empty both queues and free all bounded producer resources.


Circular GC-probe qualification must prove destination selection does not
restart at segment zero on each collection. Direct authority tests must show an
untouched later reserve is selected before wraparound to an evacuated
low-numbered victim, while preserving the exact reserve count, one-destination
rule, forbidden open/victim checks, fail-closed handoff, authoritative mapping
CRC/generation state, and foreground progress. This native evidence does not
qualify sustained loaded GC; that remains a separate release gate.


Engine-level GC rotation follows the same circular destination order as the
authority test. Compressed relocation coverage must validate byte-exact
readback and role safety without freezing the retired segment-zero restart
sequence.


Retained-target qualification requires source coverage for both closure owners:
write admission may emit PACK_READY only through the effective target helper
after refreshing accepted followers, while below-target service-proven closure
must remain in the worker after local/incoming refresh.

Tail learning must be gated exclusively by
`pack_close_pending_tail_sample`; pre-PACK sampling from a deferred first
pack is forbidden. Source coverage must also prove the zero-count flush return
precedes retained-state clearing, normal and independent retained READs refresh
accepted followers after synchronous service, and tiny dry-residue closure is
gated by read/fence evidence rather than a prior packed chain alone. After a
PACK_READY close with no already-accepted follower, that read/fence evidence
must be consumed so it cannot authorize another dry-tail singleton close.
Source coverage must preserve DUPLICATE continuation semantics because the
current WRITE continues after that older batch is flushed.

Loaded qualification must compare write-only QD8/QD32 window histograms and
lower requests against the current deep-aggregation result (~520/~139 requests),
and mixed QD32 `deadline_worker_empty` plus one-page deadline closes against
the qualified accepted-wave baseline (~60.5 worker-empty closes on the faster
model). Retained-chain and sampled-tail evidence may not survive a true worker-idle or
hard ordering boundary. The learned singleton fast-close heuristic is separate:
it intentionally survives ordinary IDLE/DEADLINE closes and is cleared by
accepted concurrency or an explicit ordering boundary.

Credited opposite-end preparation qualification requires source coverage that
the producer selects the FIFO head only while `lower_write_active` is true.
Otherwise it may select the tail only after atomically consuming
`preparation_tail_credit`, and it must reject a singular preparation queue
before consuming that credit. On a one-entry list the tail is the FIFO head;
leaving it unclaimed is the required anti-convoy cushion. The ordered worker
must reserve its head under `queue_lock` before publishing that credit.

The map path must leave a cold idle head to the ordered worker and wake the
producer only for active lower WRITE service or an already-earned atomic tail
credit. Tail eligibility stays producer-owned: source coverage must forbid
mapper-side singular-list gating and keep the producer's singular check before
credit consumption. An inline WRITE may queue the producer whenever unclaimed
preparation work exists; the producer is allowed to wake and reject a lone head
without consuming its token. `batch_count` remains worker-owned and must never
become a map-path signal; `ordered_worker_busy` is not required for a credit
that legitimately survives the inter-BIO gap of an open retained window.

For asynchronous WRITE consumption, source coverage must keep all
preparation ownership decisions under `queue_lock`. At the start of an ordered
worker quantum, a finite accepted wave may grant exactly one initial tail credit
only when at least two unclaimed WRITE preparations are already present. This is
bounded FIFO-distance evidence: the ordered worker keeps the head while the
producer may claim a distinct tail. QD1 therefore receives no accepted-wave
producer kick, and the producer's singular-list guard remains before credit
consumption.

An inline steal increments the ordered-inline diagnostic and grants one token;
a producer-owned entry records a handoff and clears any unused starter credit so
that the same ordered head cannot authorize another tail claim. `completion_done()`
distinguishes an actual blocking wait from an already-complete handoff, and the
blocking interval is accumulated separately. The producer may continue after one
tail item only when a fresh token was earned while it ran. The worker must clear
an unused token when no retained batch remains, and every nonempty window close
must clear the token after the existing zero-count early-return path. The former
`ordered_worker_busy` atomic had no reader and is dead state; source coverage
must keep it absent.

Source coverage must require both the ordered `swapz` workqueue and the
`swapz-lz4` preparation workqueue to use
`WQ_MEM_RECLAIM | WQ_UNBOUND` with one active worker. Bound preparation is a
rejected experiment. FIFO ordering and sole publication/completion ownership
remain serialized.

Loaded comparison must report producer head/tail claims plus ordered inline,
handoff and blocking-wait counts for mixed QD32 and write-only QD1/4/8/32.
QD1 must keep zero producer claims. The rejected singular-wake suppression
experiment showed that a wake which appears redundant from an instantaneous
list snapshot can still affect useful scheduling before the producer runs.
Qualification must therefore compare mixed throughput, lower WRITE requests,
worker-empty deadlines and packed-read p99 against the qualified head-cushion
source, while QD8/QD32 preserve deep-window aggregation and low blocking waits.
Mixed QD32 must also report one-page PACK_READY closes so dry-tail evidence
consumption can be rejected if it merely moves fragmentation elsewhere.
Kernel-C attribution must report explicit WRITE-copy wall/bytes, direct-LZ4
input page hits, READ-copy wall/bytes, write-engine commit time excluding
synchronous lower WRITE, and read-engine time excluding synchronous lower READ.
Write-engine attribution must additionally report planner, pack and publish wall
time. Non-I/O commit time must never exceed total commit time, and the sum of
planner+pack+publish must never exceed commit non-I/O. Publication attribution
must split the exact final-image payload `crc32c()` wall from the remaining
authority/liveness work; CRC plus authority residual must equal publication
wall for the measured interval. The CRC counter may surround only the final
payload CRC call, not descriptor decode, metadata validation or mapping work.

Source coverage must require direct mapping only for a complete single-bvec
4KiB BIO, balanced `kmap_local_page`/`kunmap_local`, retained multi-bvec
fallback, and exactly one durable RAW staging copy. Ordered/preparation callback
residency is wall time rather than CPU time and remains diagnostic only.
Pack-side CRC precomputation must retain the final payload CRC over
`bulk_scratch` during publication.

The completed dry PACK_READY arrival timer/histogram is retired. Lower-WRITE
starvation attribution instead maintains an exact unclaimed preparation
descriptor count under `queue_lock` and samples that count at synchronous
lower-WRITE start/end without changing scheduling, retention, credits or worker
count. Nonempty-event counts may never exceed lower-WRITE sample count and
queued totals may never be smaller than their corresponding nonempty counts.
Write-only QD1 remains producer-free and lower-byte/read-tail gates remain hard.
All publication/completion/fail-closed invariants are unchanged.

Idempotent metadata-cache invalidation qualification must preserve the existing
explicit-invalidation and post-write miss tests. Source coverage requires the
512-slot validity clear to remain present but guarded by a nonzero metadata-LRU
clock, with the clock reset inside that guarded block. Native coverage must call
the mutation fence twice before a reread and still require a lower metadata
read, proving repeated invalidation changes no observable authority behavior.


Source-contract maintenance must follow the same standards co-change rule as
production implementation work. When an implementation invariant moves between
owners (for example, PACK_READY closure from write admission to the serialized
worker), contract assertions must move with that ownership in the same
standards-backed change rather than preserving historical body-local syntax.


Only a successful PACK_READY continuation may arm post-I/O admitted-tail
sampling. Other retained chain continuations such as duplicate/full or
already-accepted zero/raw interruption may carry bounded service/count evidence
within the same worker burst, but must keep
`pack_close_pending_tail_sample` false so they cannot infer a residual tail
from a non-PACK close.


Nonblocking preparation-slot qualification requires the producer to call
`down_trylock(&ctx->preparation_slots)` before acquiring `queue_lock` or
removing a preparation entry. No blocking `down()` may remain in the
producer. Every return after a successful slot reservation but before BIO
claim must `up()` the slot. Existing producer error paths and ordered
prepared-page release must continue to return exactly one slot. This prevents
tail preparation at queue depths above the 64-record bound from creating a
FIFO/semaphore deadlock.


### Lower-WRITE queue starvation and GC distribution attribution

The retired dry-close timer answered its bounded scheduling question and is no
longer production telemetry. The active starvation probe is observational:
`preparation_queued` counts unclaimed preparation descriptors exactly under
`queue_lock`; every synchronous lower WRITE records queue depth and whether it
is nonempty immediately before `dm_io()` and immediately after it returns.
The probe must not grant credits, wake extra workers beyond the existing wake,
extend retention or alter completion ownership.

Live-GC distribution attribution increments a per-segment eviction counter only
after a successful committed victim rotation. Loaded qualification reports the
number of distinct victim segments and min/max evictions among used victim
segments. This establishes synthetic reuse-distribution evidence; it is not a
physical wear claim and is a prerequisite to any DISCARD/TRIM experiment.

Top-level qualification status follows the classified stage result, not a raw
child exit-code convention. A stage classified FAIL remains overall FAIL even
when its shell helper returned 2; BLOCKED is reserved for an explicit blocked
stage marker.


### Immutable ping-pong lower-I/O qualification

A write run may become asynchronous only after its mutable engine buffers and
transaction state have been moved into a caller-owned immutable run object.
Submission completion callbacks must never observe reused `bulk_scratch`,
`bulk_txs`, batch hashes, upper-BIO pointers or ordering flags.

The active collector and immutable streaming run are separate ownership
domains. The collector performs zero detection, LZ4 and payload CRC while the
previous run is in lower I/O. Freezing a collector forbids further mutation; it
does not start compression. Planning/packing may use the exact prepared lengths
before submission.

For a serial-depth experiment, keep exactly one lower run outstanding while a
second ownership domain collects/prepares the next run. Do not force smaller
runs merely to manufacture overlap. A candidate fails if lower WRITE bytes or
request count regress materially, if a well-packed QD wave is fragmented
without compensating useful throughput, or if any generation/order/read-tail
gate regresses.

For parallel-depth experiments, retain one global collector/planner and vary
only the number of immutable lower runs allowed in flight. Start with explicit
K values rather than protocol-name assumptions. Per-lane independent write
accumulators are not the default because they reduce the global set available
to the packing planner.

A latency-sensitive READ queue must bypass batching when lower I/O is idle.
Any busy-time coalescing/reordering experiment requires private request/run read
scratch and same-page dependency checks against active/frozen/in-flight writes.


### Report publication authentication and concurrency

The report publisher must preserve the operator's configured noninteractive Git
credential helper or askpass mechanism. It may set `GIT_TERMINAL_PROMPT=0`
and SSH batch mode so qualification never waits for an interactive password,
but it must not blank `GIT_ASKPASS` or disable a configured credential
manager.

A separate `ls-remote` authorization probe is not required. The generated
report commit has the exact tested source commit as its parent and is pushed
normally (never force-pushed) to `main`. Therefore a concurrent advance of
`origin/main` makes the push non-fast-forward and Git rejects it.

### Generated report versus tracked source cleanliness

`test_results.json.xz` is the one generated overwriteable evidence file and is
not tested source. Privileged loaded qualification therefore excludes only that
exact root path from its tracked/staged source-cleanliness check. This permits a
previous local report to remain until the current run finishes, including after
an earlier publication failure. Every other tracked or staged change still
blocks loaded qualification before module/device work.


Immutable-run native qualification must accept a bounded prepared prefix rather
than assuming an arbitrary logical window fits one physical run. Tests walk
successive prepare/complete cycles until the complete logical window is
published, while each individual prepared prefix remains immutable and
unpublished until its own lower completion. A failed first prefix must publish
nothing and quarantine all reservations belonging to that prefix.


Source contracts for the immutable-run split must assert semantic ownership,
not retired helper names. The prepare function may test whether a synchronous
write callback is configured, but it must not invoke that callback. Lower I/O
submission remains in the synchronous wrapper until the target-side async
candidate is enabled; transaction replay and publish timing belong to the new
completion function.


Phase-wall source contracts follow the new immutable-run ownership: planning
and packing attribution live in run preparation, while publication attribution
lives in run completion. The synchronous compatibility wrapper is orchestration
and lower-I/O submission only; it must not duplicate those phase timers.


### Privileged Git inspection must not mutate the checkout index

Loaded qualification executes its device helpers as root, but their Git checks
are source-identity/read-cleanliness assertions only. Every privileged helper
that invokes Git must set `GIT_OPTIONAL_LOCKS=0` before the first Git command.
This forbids optional index refresh/locking during root-side `git branch`,
`git diff`, and `git rev-parse` inspection, preventing a successful
qualification from replacing the operator-owned `.git/index` with a
root-owned file. Privileged helpers must never stage, refresh, rewrite, or
otherwise own the checkout index.


### Explicit lower queue geometry

Performance null_blk models pin and reread queue geometry before power-on. The
slow profile is blk-mq queue_mode=2, submit_queues=1, hw_queue_depth=1. The
fast profile is queue_mode=2, submit_queues=1, hw_queue_depth=64. The report
records these values with bandwidth and timer latency; mismatch is incomplete.
Loaded correctness smoke also uses depth 1. These are synthetic queue models,
not literal SD/HDD/SSD/NVMe protocol emulation.

Each timed benchmark arm samples only its positively identified owned lower
device's `/sys/block/<disk>/inflight` counters. The sanitized report records the
target sampling interval, achieved sample count, initial/last sampled
READ/WRITE depth, sampled peaks and sample-and-hold time-weighted means.
Sampling is observational and is not an exact per-request trace; the achieved
sample count stays visible so sparse evidence cannot be mistaken for complete
queue history.

For swapz mixed arms, the kernel also reports K=1 immutable-run occupancy as
wall time from setting `inflight_write.active` before asynchronous `dm_io`
through ordered authority publication and release of the run slot. This
occupancy intentionally includes callback-to-worker scheduling delay and
publication; it is distinct from lower-WRITE device wall time and from the
preparation backlog. Synchronous arms must report zero asynchronous run
occupancy.

### Compound/folio bvec iteration

Do not apply nth_page() to a bvec returned by bio_for_each_segment() merely
because its stored source bvec may span a folio. Linux bvec iteration advances
the page and normalizes the iterator offset to a single-page segment. The copy
path therefore maps vec.bv_page and uses its page-local vec.bv_offset. A
page-aligned 4KiB folio slice can already reach the direct single-segment path;
multi-segment slices retain the copy fallback.


### Native Make-interface benchmark fixture fidelity

The unprivileged Make-interface qualification may replace the privileged loaded
stage with deterministic synthetic output, but that fixture must mirror every
field that the real report parser treats as benchmark-model identity. When
lower queue geometry is part of the model contract, fake
`PASS_RAM_MODEL_LOWER_MBPS` records must include the exact queue mode,
submission-queue count and hardware queue depth for each regime. A parser
schema change must update this fixture in the same change so rootless
qualification cannot pass evidence that a real loaded run would reject.


The write-only saturation parser consumes the same exact owned-RAM device-model
identity as the mixed benchmark parser. It must validate queue mode,
submission-queue count and hardware queue depth in addition to bandwidth,
completion delay and IRQ mode; a private pilot may not silently accept a
different lower queue geometry from the mixed qualification.


### Report-contract fixture model identity

Native report-contract fixtures must emit the complete configured storage-model
identity accepted by the production parser. Mixed and write-only synthetic logs
therefore carry queue mode, submission-queue count and hardware queue depth as
well as bandwidth, completion delay and IRQ mode, and their expected
`device_model` dictionaries compare all six fields.


### Timed scheduling attribution

The loaded replay snapshots all window-size bins, close reasons, one-page close
reasons, deadline contexts, retained-burst counters, preparation counters and GC
victim count immediately before the first measured wave and after the required
measured final fsync. Reported mixed and write-only scheduling tables use only
those interval deltas. The outer helper's full-process `SWAPZ_STATUS_BEFORE`
and `SWAPZ_STATUS_AFTER` may include prefill, warmup and packed-read population
and therefore are not report evidence for timed scheduling decisions.
`retained_burst_target` is recorded as the end-of-interval gauge.

The direct rootless unit for this measurement schema lives at
`tests/runtime/benchmark/io-replay-test.py`; report aggregation and Make-interface
fixtures remain under `tests/runtime/native/`. When the timed schema gains a
counter or gauge, all three fixture surfaces must be updated together so a
rootless pass cannot hide a missing loaded-report field.

Source coverage requires an explicit ordering-boundary predicate that clears the
learned singleton deadline streak and fast-close flag before the empty-window
return. IDLE and DEADLINE must remain outside that predicate. Native/report
fixtures must prove that altering full-process status cannot alter the timed
window verdict while malformed timed close/deadline accounting fails closed.

### Partial 4-block read-cache qualification

Direct production-C engine coverage must create a seven-record 16KiB extent and
read its sibling records sequentially. With one immutable extent resident, each
of its four physical blocks may be fetched from the lower device at most once,
all logical payloads must remain byte-exact, and the complete-block mask may be
published only after successful lower reads and normal authority/CRC validation.
Explicit invalidation and a subsequent production write must clear payload
residency. Device Mapper source coverage must retain the existing non-READ
mutation fence so discard/barrier/write paths cannot reuse stale payload blocks.

Transaction-snapshot CRC attribution is measurement only. Pause and resume must
have separate wall counters whose sum exactly equals the retained aggregate.
Pause is outside engine publish and may be reconciled from commit residual;
resume is already inside publish authority and must not be subtracted twice.
Both paths continue to hash the complete `struct swapz_tx`; adding the split
must not change hash length, identity checks or publication semantics.

One-page PACK_READY cause attribution remains exact. The repaired READ baseline
confirms 78.0 sampled-tail / 24.2 read-bypass / 0 wave-interruption on the fast
model and 0/0/0 on the slow model, so the dominant-cause measurement is closed.
For every timed `win1_pack_ready`, exactly one T/R/W counter must still increment
and their sum must equal `win1_pack_ready`; ID50 must not make suppressed tail
closes reappear under the read-bypass or wave bucket.

### Sampled-single-tail PACK_READY qualification

Direct policy coverage must prove a sampled admitted tail of one cannot close a
one-record window early, while sampled tails of two and three can close at their
exact one-shot targets. Source contracts must prove `tail == 1U` updates learned
burst width, clears the one-shot tail target and sets
`retained_single_tail_deferred`; multi-record samples arm the exact tail target
and clear the deferral.

Both `swapz_retained_target_close_ready()` and
`swapz_retained_pack_close_ready()` must refuse a deferred singleton. The
second admitted record clears the deferral, and real nonempty flushes, hard
boundaries and true empty burst boundaries clear it as well. After ID53
rejection, source/native contracts must prove no shorter singleton deadline,
cutoff watermark or hrtimer reprogramming remains: the ordinary first-record
deadline is the only retained deadline.

The owner-qualified ID50 mechanism remains active after the ID53 rollback.
Qualification must preserve exact deferred-singleton lifecycle conservation,
prevent sampled-tail singleton PACK_READY closes from reappearing under
read-bypass/wave labels, and reject any successor that materially grows lower
WRITE bytes/requests or regresses useful mixed throughput/read tails.

### Deferred-singleton outcome attribution

ID51 is instrumentation only. Production code must expose cumulative
`single_tail_deferrals`, `single_tail_companions`,
`win1_deadline_deferred_tail`, `win1_idle_deferred_tail` and
`single_tail_other_clears`. Direct source coverage must prove every clear site
accounts before clearing and that companion admission resolves exactly once.

The mixed benchmark snapshots these counters around the same timed waves as the
existing window telemetry. Because every closed-loop wave is fully acknowledged
before the next wave and the final snapshot follows `fsync`, no deferred
singleton may straddle a timed boundary. Both replay validation and report
validation therefore require exact delta conservation:
`D == C + DL + I + O`, with `DL <= win1_deadline` and
`I <= win1_idle`. Missing or inconsistent telemetry fails qualification.

The operator report must print the compact row `deferred tail D/C/DL/I/O`;
rootless report-contract coverage must assert that row is present so schema
plumbing cannot silently omit the new lifecycle evidence. ID51 answers where
ID50 work goes; it does not itself justify another retention rule. Any successor
must be a separate source revision after owner evidence.

### Deferred-singleton timing/service evidence

ID52 extends ID51 without changing policy. Timed replay validation must require
that the four companion-age bins sum to `single_tail_companions` and the four
deadline-age bins sum to `win1_deadline_deferred_tail`. After the ID53
rollback, the four passive companion sub-bins 1001-1250/1251-1500/1501-1750/
>1750 us must sum exactly to the aggregate >1000 us companion bin. For
companion and deadline service attribution, lower-done and read-bypass counts
cannot exceed the terminal total, and the both count cannot exceed either
subset. The report must print both original age rows, the upper-tail companion
row and both L/R/B service rows.

Interpretation is predeclared: an event such as lower-W completion or READ
service is not a candidate early-close discriminator if it commonly occurs
before companion resolutions as well as deadline resolutions. A successor
policy requires a separate source revision after owner evidence.

### Rejected ID53 rollback and passive attribution qualification

Owner evidence rejected the fixed 1 ms active cutoff: 13.8 of 31.5 cutoff
closes were followed by an ordinary WRITE before the original deadline. Direct
source/native coverage must therefore prove `SWAPZ_SINGLE_TAIL_CUTOFF_NS`,
the single-tail cutoff deadline helper and cutoff/watermark production counters
are absent, while ID50 still blocks a one-record deferred singleton until a
companion or the ordinary deadline.

ID54 PACK_READY attribution is measurement only. Every timed PACK_READY close
must increment exactly one of `pack_close_tail_target`,
`pack_close_burst_target` or `pack_close_service_dry`; their sum must equal
`close_pack_ready`. `pack_close_tail_target_le4` must not exceed the tail
counter. The operator report must display tail<=4/tail/burst/dry separately for
sync and async and, on the fast five-pair model, print paired async-minus-sync
95% CIs for those causes plus mixed throughput and absolute lower-request
delta. Never average sync/async causes into an “async signal” row.

ID55 remains measurement only. For every learned burst-target close,
`pack_close_burst_admission + pack_close_burst_worker` must equal
`pack_close_burst_target`; the four learned-target bins and four actual-count
bins must independently sum to that same total, and overshoot cannot exceed it.
The compact report prints sync/async/delta plus fast paired confidence intervals.
Source contracts prove admission/worker snapshot the existing learned target
without changing readiness.

ID56 first-observation conservation remains mandatory: the six post-PACK
tail-size/state buckets (0/1/2+ crossed with active K=1 vs idle) sum exactly to
`pack_tail_samples`; deferred ID57 re-samples do not double-count that total.

ID57 is an active bounded experiment. Source contracts must pin the busy helper
to active && !completion_done, require admission and worker PACK_READY paths to
count-and-defer only while that helper is true, and prove the sampler can return
with its pending sample/chain intact for zero-tail active or completion-only
holds. The deferred sample must be retried before processing a nonempty next
local wave. No new timer, sleep, spin or K>1 slot is allowed.

ID57 lifecycle validation must be boundary-aware. A deferred-zero lifecycle may
begin before a timed mixed/write-only snapshot and resolve or abort inside that
interval. Derive the one-bit start/end state from cumulative counters as
`deferrals - (resolve0 + resolve1 + resolve2plus + aborts)`; each cumulative
snapshot must yield exactly 0 or 1. Timed conservation is exact only when
`start + interval_deferrals == interval_terminals + end`. Completion-only
holds are bounded by `start + interval_deferrals`; post-finalization closes
remain a same-event subset of timed packed-early closes. Never reject valid
evidence merely because a lifecycle crosses the measurement boundary.
Rootless report fixtures must include both a valid carry-in resolution with
zero same-interval deferrals and an impossible cumulative lifecycle that fails
closed.

Synthetic ID57 fixtures must preserve the same subset invariants as runtime
telemetry: a nonzero post-finalization close requires a corresponding packed
early close, and source-string contracts must follow the current three-argument
tail-sampler call rather than pinning its pre-ID57 signature.

ID24 boundary CPU attribution is measurement only and is not a trustworthy
total for short callbacks. Status/timed deltas retain
`ordered_worker_cpu_ns`, `prep_worker_cpu_ns` and `read_worker_cpu_ns` as
scheduler-accounted lower bounds. They must also expose separate
`ordered_lz4_wall_ns`, `prep_lz4_wall_ns`,
`ordered_write_copy_wall_ns` and `prep_write_copy_wall_ns`. The report shows
callback wall, scheduler lower bound and measured non-sleeping phase floors
separately. No worker-count/affinity conclusion may rely on the boundary
`sum_exec_runtime` value alone.

### Same-cache Kread A/B confirmation

The loaded test runs exactly ten SSD_EMULATED sessions in fixed order
`parallel_reads=0,1,1,0,0,1,1,0,0,1`, with `async_prepare=0`, identical
source/fixture/trace and alternating raw/swapz replay order. Adjacent sessions
form five counterbalanced Kread-off/on matched rounds. The Kread-off arm must
report zero `parallel_read_pairs`; every Kread-on packed pass must report
positive pair activity before latency comparisons are accepted. Each packed
pass remains 4 MiB/1024 verified pages.

For sequential and seeded-random reads, report paired on/off change fractions
and two-sided Student-t 95% confidence intervals for p99, useful throughput,
lower bytes and lower requests. Promotion requires a repeatable latency benefit
without material traffic inflation; a confidence interval is evidence, not a
license to ignore the physical-I/O gate. If lifecycle qualification passes but
this A/B contract fails, the loaded stage must fail with the A/B evidence reason
rather than attempting to read a lifecycle failure reason from a passing
lifecycle result. Failure-path report fixtures must identify the Kread
confirmation reason explicitly rather than the retired diagnostic label.

The standard mixed report must also expose existing sync/async window bins
(win1, win2, win3_4, win5_8, win9_16, win17_64) plus PACK_READY/DEADLINE/IDLE
close totals. Do not add multi-tail kernel instrumentation unless these existing
bins leave the residual fragmentation question unresolved.

### Bounded Kread=2 qualification

The owner-qualified `bd3f5886b61a...` implementation is a rejected
implementation of the latency-first READ idea: it raised fast lower READ peak
to 2 and improved fast random p99, but fragmented metadata/extent residency and
increased lower READ bytes/requests by roughly 35-159%, including a severe
serial-depth regression. A faster latency result that spends substantially more
physical I/O fails the endurance-first acceptance gate.

The revised experiment must prove exactly two bounded slots, queue-depth gating
through the backing request queue, no slot allocation/workqueue at depth one,
private helper engine state, and ordered-owner-only shared cache mutation. The
read-only `parallel_reads` module parameter defaults true and may disable Kread
for same-cache A/B evidence; depth-one remains serialized even when enabled. Direct
production-C coverage must prove a 16-entry extent cache retains eight
interleaved four-block extents without duplicate block reads, and that
`swapz_engine_prime_read_slot()` / `swapz_engine_absorb_read_slot()` preserve
extent residency plus metadata-LRU reuse across helper execution.

Loaded acceptance is stricter than the report's latency-only `FASTER` label.
The depth-one model must return to the serialized baseline with no material
lower-byte/request or p99 regression. On the depth-64 model, Kread=2 must again
raise lower READ depth above one and improve useful packed-read latency, while
sequential and random lower bytes/requests stay at or below the qualified
`89fe711...` cache baseline within ordinary run noise. Any candidate that buys
latency with material read amplification is rejected.

The ready-prefix scan stops at the first non-independent BIO. Pulling a later
sibling is allowed only across skipped BIOs that are themselves independent
READs; no write/barrier/dependency may be crossed. A single eligible READ never
waits for a partner. Two synchronous slot callbacks can overlap, so summed lower
READ busy-wall counters are not elapsed pair wall; use sampled lower in-flight
depth and end-to-end latency/throughput together with lower bytes/requests.

Source-contract assertions follow ownership helpers rather than retired syntax.
A grouped dispatch may consume more than two BIOs, so worker-quantum coverage
must require `remaining -= processed_bios` and an exact processed count returned
by the grouped-read helper rather than a hard-coded paired value.

The existing one-block selective-read budget remains an exact compatibility
contract. `read_cached_full` denotes reusable multi-block extent residency; it
must remain false for one-block extents and when `max_read_blocks_per_record ==
1`, even though `read_cache_valid` and the exact block mask may be populated.
The shared extent cache is bypassed under the one-block budget.

Under `max_read_blocks_per_record == 1`, selectively fetched payload blocks are
not added to reusable residency either. A later logical read must exercise its
own bounded lower payload callback; an injected failure on that callback must
still fail the read and invalidate the volatile header cache.

Source coverage for partial extent residency must assert semantic gates rather
than obsolete spellings: metadata hits merge block-zero into the mask, reusable
payload residency is limited to multi-block extents outside the explicit
one-block budget, and `read_cached_full` is likewise multi-block/budget-gated.

ID52 status labels may abbreviate `companion` as `comp` for operator output,
but source contracts must bind each label to the exact backing struct member so
schema spelling and production accounting cannot silently diverge.

Rootless console-report coverage must pass the parsed ID39 diagnostic object to
the printer; a display assertion is not valid against a report that omits the
A/B evidence object entirely.
