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
5. Owned RAM-backed `null_blk` correctness, lifecycle/fault checks, matched mixed benchmark pairs and the bounded write-only QD pilot.

Stages are ordered and fail fast. Privileged device sessions must never overlap. If noninteractive privilege or safe owned-device provisioning is unavailable, the complete run reports BLOCKED rather than silently skipping loaded work.

## Direct production-C tests

Native tests compile the real `src/kernel/{codec,authority,engine}.c` where applicable. They cover codec integrity, authority publication, torn/short failure, overwrite generations, discard, zero-write representation, online packing, randomized authority, lower-run aggregation, flush/FUA accounting, retention/window policy and GC rotation/cost invariants.

Source contracts validate behavior that requires the Linux Device Mapper target itself, including BIO ownership, queue/drain ordering, null_blk-only admission, lower-I/O accounting and current report/build contracts. Source-string assertions are secondary to executable production-C coverage.

## Loaded correctness

Loaded tests use only newly created, positively owned, RAM-backed `null_blk`. Before and after use, verify device identity, size, major/minor, DM UUID, holders, mounts and active-swap aliases. Never substitute a physical or existing block device.

The deterministic lifecycle oracle must preserve exact readback, RAW fallback, zero elision and explicit flush behavior. Retained-window suspend/resume must drain accepted ownership and verify all pages. Synthetic pre-submission WRITE and FLUSH injection must fail closed. These synthetic failures are not evidence for torn/device-originated errors.

Cleanup never force-removes uncertain resources. If identity or teardown is ambiguous, quarantine and fail.

## Benchmark pairing and provenance

The mandatory mixed matrix uses two RAM-only latency models: 10 MiB/s with 1 ms completion and 80 MiB/s with 0.15 ms completion. Each model has four counterbalanced pairs across synchronous/asynchronous preparation. The control candidate is `off`; the product candidate is `swapz`.

Both arms of every pair carry the same exact source SHA, fixture SHA-256 and trace SHA-256. Missing or divergent provenance is INCONCLUSIVE. Every logical workload must finish its byte-exact oracle before a performance verdict is considered.

The write-only saturation pilot uses QD1/4/8/32 under the same two models with one sync and one async pair per QD. Until at least five counterbalanced pairs per mode/QD/regime and confidence intervals are implemented, it is directional only.

## Report contract

Official human-readable and JSON reports use `swapz`, not implementation-generation labels. Schema keys are version-neutral. SWZ3 is reserved for on-disk format discussion.

Reports distinguish useful logical throughput, backing WRITE throughput, lower READ/WRITE bytes and requests, p95/p99 where available, process CPU scope, kernel counters, GC, fixture/trace/source provenance, lifecycle result and cleanup. Never call synthetic RAM results physical SD/SSD evidence.

The console report is a compact operator summary. It keeps raw and synchronous
throughput controls because they isolate compression and asynchronous scheduling
effects, but suppresses repetitive per-control diagnostics. Detailed cache,
window and counter evidence remains in the replace-in-place
`build/test_results.json.xz` report.

The retained production counters must describe active decisions only. Closed/rejected diagnostic counters are removed from production and report schemas.

## Evidence levels

Source contracts show structure, not loaded semantics. Native C shows portable product logic, not Device Mapper runtime. W=1/W=2 shows compilation, not correctness. Owned RAM-backed loaded tests show real kernel BIO behavior on the test host, not physical-media benefit. Only separately authorized physical testing can establish behavior on a particular real device.

## Current qualified baseline

Source `f10a1e0173f45e6daf52773d0b4a559b7df7ddb7` passed all five stages and is
the accepted directional performance baseline. It preserved byte-exact loaded
correctness, retained suspend/drain, RAW/zero/flush behavior and synthetic
WRITE/FLUSH fail-closed checks while retaining the large random-read lower-byte
reduction and recovering the earlier QD8 regression. Its QD pilot remains
one-pair exploratory evidence without confidence intervals, and live GC remains
unexercised.

## Open qualification gaps

Genuine device-originated/partial lower errors, long-run resource pressure, larger controlled cold-read working sets, exact portable kernel-worker CPU attribution and statistically repeated QD saturation remain open. Sustained live GC is now an owned-RAM qualification gate: it must complete multiple victim rotations with byte-exact verification and reuse-distribution evidence. Physical-media testing remains blocked pending separate authorization and safety review.


Source contracts should assert retained scheduling semantics rather than a
particular obsolete branch spelling: retained writes must reach the ordered
worker immediately, while retention-off ordinary writes retain zero-delay
single-instance queueing.


The canonical report is local evidence at `build/test_results.json.xz`.
`make test` must not create commits, push Git refs, or alter the checked-out
source revision. A report describes the exact tested checkout; publishing or
archiving it is an explicit owner action outside qualification.


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
all accepted pages. Its status sampler starts before the private writer and
polls without an added sleep so adaptive singleton fast-close cannot hide the
initial full-retention opportunity behind userspace process-start latency. It
must still observe `retain_timer_arms > windows`; historical timer activity is
not a substitute for an actually open window. The maximum supported 4ms
deadline can legitimately expire between that observation and the separate
suspend request, so the oracle must not require a specific close-reason counter
afterwards. Loaded failure reporting skips the generic cleanup epilogue so the
preceding specific sanitized failure remains visible.


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
model). No scheduling evidence may survive a true worker-idle or hard ordering
boundary.

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
planner+pack+publish must never exceed commit non-I/O. Source coverage must
require direct mapping only for a complete single-bvec 4KiB BIO, balanced
`kmap_local_page`/`kunmap_local`, retained multi-bvec fallback, and exactly
one durable RAW staging copy: mapped input directly to `batch_bytes` in bulk
mode, or the existing `swapz_raw_write()` BIO copy in non-bulk mode. Source
coverage must reject the retired mapped-input -> `input_page` -> `batch_bytes`
bounce. Exact worker CPU counters must not rely on raw scheduler-private fields or
claim that `task_cputime_adjusted()` captures every short current slice.
Portable callback-active wall upper bounds must account every callback return,
subtract only independently measured waits, expose subtraction underflow as a
fail-closed diagnostic, and remain policy-independent. Write-only QD1 must
remain producer-free,
QD8/QD32 must keep ~520/~139 lower WRITE requests, and lower-byte/read-tail
gates remain hard. The existing `prep_lower_write_overlap_starts` diagnostic
remains meaningful, and all publication/completion/fail-closed invariants are
unchanged.

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


Loaded GC qualification must run only on the same freshly owned, positively
identified RAM-backed null_blk safety path. It must start from a fresh swapz
mapping, apply bounded scattered overwrites that preserve live survivors across
old segments, verify every logical page against its latest expected generation,
and require nonzero relocation READ/WRITE I/O. A passing run requires at least
four successful victim/role rotations, multiple distinct victim and destination
segments, no failed target state, and reported maximum reuse below the total
rotation count. This evidence qualifies the GC mechanism on synthetic RAM; it
does not establish physical flash endurance or authorize physical media.

Precomputed foreground payload CRC qualification must prove that the CRC is
computed over the exact compressed bytes, carried through admission/planning,
and consumed only by the pack-side prehashed append. Source and native tests
must also prove that `swapz_finish()` still verifies payload CRC over the final
extent image before publication. Dry-close arrival timing is diagnostic only:
recording a timestamp may not delay, recheck, cancel or otherwise influence a
PACK_READY decision.
