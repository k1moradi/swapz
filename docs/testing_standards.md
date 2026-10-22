# Testing Standards

**Immutable naming policy (read before every prompt):** The project is `swapz`; the kernel module is `dm-swapz.ko` (loaded as `dm_swapz`); the Device Mapper target is exactly `swapz`; and the module alias is `dm-swapz`. Never put implementation-generation numbers in product, module, target, source-path, report, workflow, helper, or schema names. `SWZ` is the current unversioned on-disk format identity; do not assign a format version until an incompatible format boundary is justified.

**Single official test command (read before every prompt):** Run `make test` at the repository root for every supported swapz test and benchmark. A complete run must report BLOCKED (nonzero) if safe noninteractive privileged qualification cannot run. Do not create, publish, recommend, or document alternative test commands. Private scripts and CI jobs are implementation details, not operator interfaces.

## Official interface

The root checkout has one supported testing interface:

~~~sh
make test
~~~

When the caller does not provide a GNU Make jobserver, the private reporter
automatically chooses a bounded build width from the CPUs available to the
process (maximum 16) and creates jobservers only for independent compilation.
An inherited jobserver takes precedence. Operators do not need to choose a
manual `-j` value; qualification stages and privileged device sessions remain
strictly sequential.

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

Before any owned RAM device is provisioned, loaded qualification may ordinarily
unload a pre-existing `dm_swapz` module only when
`/sys/module/dm_swapz/refcnt` is readable, numeric and exactly zero. This
preflight never removes a Device Mapper mapping, never changes swap and never
uses forced module removal. A positive, unreadable or changing reference count
is BLOCKED. The final ordinary `rmmod` is still authoritative against races:
if a user appears after the zero-refcount observation, removal fails and
qualification stops.

Cleanup never force-removes uncertain resources. If identity or teardown is ambiguous, quarantine and fail.

## Benchmark pairing and provenance

The mandatory mixed matrix uses two RAM-only latency models: 10 MiB/s with 1 ms completion and 80 MiB/s with 0.15 ms completion. The slow model remains a bounded four-session directional control (two sync, two async). The fast model runs ten sessions in the fixed sequence `0,1,1,0,0,1,1,0,0,1`, which forms five adjacent counterbalanced sync/async matched rounds. The control candidate inside every session is `off`; the product candidate is `swapz`.

Both arms of every session carry the same exact source SHA, fixture SHA-256 and trace SHA-256. Missing or divergent provenance is INCONCLUSIVE. Every logical workload must finish its byte-exact oracle before a performance verdict is considered. The five fast matched deltas use a two-sided Student-t 95% confidence interval with four degrees of freedom. Report both the paired mean and interval; do not replace paired analysis with an interval over unpaired arm means.

The write-only QD1/4/8/32 sweep is sustained offered-load evidence: workers are pre-created, warmup finishes before a common measured start gate, and each worker owns a disjoint ordered logical-page lane. No per-I/O Future submission or full-QD wave barrier is permitted in the timed path. Slow QDs and fast QD1 stay directional; fast QD4, QD8 and QD32 each use the ten-session confirmation sequence and paired 95% confidence intervals for logical write throughput, lower requests and lower bytes. This produces exactly 40 write-only sessions across both synthetic regimes. Historical wave-driver intervals are burst evidence only and cannot promote sustained-QD performance. Rootless Make-interface/source fixtures must assert the shared sequence, persistent replay mode and fast-QD4/QD8/QD32 mode selection.

## Report contract

Official human-readable and JSON reports use `swapz`, not implementation-generation labels. Schema keys are version-neutral. SWZ is the current unversioned on-disk format identity.

Reports distinguish useful logical throughput, backing WRITE throughput, lower READ/WRITE bytes and requests, p95/p99 where available, process CPU scope, kernel counters, GC, fixture/trace/source provenance, lifecycle result and cleanup. Never call synthetic RAM results physical SD/SSD evidence.

The console report is a compact operator summary. It keeps raw and synchronous
throughput controls because they isolate compression and asynchronous scheduling
effects, but suppresses repetitive per-control diagnostics. Detailed cache,
window and counter evidence remains in the single replace-in-place
root `test_results.json` report.

Every console table printed by the official `make test` reporter must have a
clear, self-contained Markdown title immediately before an unindented
GitHub-Flavored Markdown pipe table. The title names the measurement, workload
or comparison without depending on a nearby section heading. Header-separator
cells use explicit left alignment with a leading colon and at least three
dashes. Each table is followed immediately by a legend that defines every
column, including whether higher, lower or zero is preferred when that
direction is meaningful; context-dependent diagnostics are labeled descriptive.
An automated interpretation derived from the rows follows the legend, and a
literal `---` horizontal rule follows the interpretation. Paired
confidence-interval interpretations must say whether intervals exclude or
overlap zero; descriptive tables must not imply that the largest value is
automatically best. Operator-facing headings and scope names use plain,
human-readable descriptions rather than roadmap IDs. Keep every printed line
under 96 columns so captured stdout stays copy/pasteable and readable.
Legends must distinguish a ratio from its percentage change. READ rates and
latencies from the mixed interval must be labeled as mixed-load observations;
only the separately measured `packed_read` passes describe the 4MiB read phase.

Background work, including Codex and editors, is part of the host's load.
Collect `/proc/stat` and CPU PSI `some total` snapshots around each mixed,
write-only and fixed-volume READ phase. Report online/affinity CPU counts,
active and steal fractions, PSI waiting fraction and replay-process CPU usage.
Snapshot reads occur outside the throughput stopwatch; their own boundary span
is recorded. No additional polling worker is required. Missing, reset or
unavailable counters must appear as unavailable, never zero. Whole-host active
time includes benchmark/kernel work and does not attribute cost to Codex.

No report from this matrix establishes an idle-host control. Counterbalanced
pairs limit ordering bias but cannot remove time-varying background load.
Earlier idle-host runs and runs with Codex active are different conditions;
do not pool them or attribute their differences to code without equivalent
resource conditions. Do not subtract estimated application CPU from measured
throughput. Host metrics also do not replace the independent low-RAM/heavy-CPU
release gate.

Loaded qualification of the default-on preparation path must read the target's
status after every bare module load and fail unless `async_prepare=1`, including
after a module reload. Paired synchronous controls must pass
`async_prepare=0` explicitly and verify the reported mode.

The retained production counters must describe active decisions only. Closed/rejected diagnostic counters are removed from production and report schemas.

## Evidence levels

Source contracts show structure, not loaded semantics. Native C shows portable product logic, not Device Mapper runtime. W=1/W=2 shows compilation, not correctness. Owned RAM-backed loaded tests show real kernel BIO behavior on the test host, not physical-media benefit. Only separately authorized physical testing can establish behavior on a particular real device.

## Current qualified baseline

The latest successful standard owner matrix tested source
`5bf2c0a6f0384ccf3829dc02dc0e9b737c857e40`, passed all five stages, and
published report-only commit
`85aeac4cbb368bb4900cd94c9c73f46d952520ef`. This qualifies alpha.26's
metadata-key deduplication, final producer drain and aligned preparation array
on owned RAM-backed `null_blk`.

The later owner run for `b7aae67fc230ceb4323e8be4c6f1ebf219cba405` failed in
stage 2 before loaded qualification because the native source-contract parser
did not recognize alpha.27's `swapz_u16` metadata-cache helper. Report-only
commit `7faef62418e9563efde947cef432e63af1236629` correctly records overall
FAIL and loaded `NOT_RUN`. Commits
`55183d7c7d041c74068ed553ba42213fc44cf713` and
`30ba10ce38ebae3da2e401bba15b1ca4178765c5` repair and pin only that parser
defect; they do not promote alpha.27 without another complete owner `make test`.

Against the preceding `9a802eff` report, fast random backing reads fell from
3592 to 2993 KiB and 734.6 to 678 requests. Directory hit rate rose from 71.2%
to 86.8%; random replacements fell from 309.4 to 134.4, sequential from 441 to
43. These cross-run observations support the duplicate-key repair, while the
remaining I/O difference from the older `5bdd040` baseline motivates a bounded
two-choice cache experiment. Host load and post-write geometry prevent a clean
causal attribution of the entire remaining difference to set conflicts.

Five matched fast-model async/sync write pairs measured QD4 -0.4% (95% CI
[-4.4%,+3.6%]), QD8 +28.7% ([+21.9%,+35.5%]), and QD32 +27.1%
([+21.8%,+32.5%]). QD8 requests fell 23.7% and bytes rose 0.55%; QD32
requests rose 17.7% and bytes 0.72%; all four intervals exclude zero.
Fast mixed throughput +3.2% ([-1.9%,+8.4%]) is inconclusive versus sync.
Rescue remains off with zero classifier/transform activity.

Fast QD32 whole-host CPU activity averaged 42.2% sync versus 55.0% async;
CPU PSI averaged 20.5% versus 27.0%. These include benchmark, kernel and
background work such as Codex. They do not isolate swapz CPU or establish an
idle-host control. Low-RAM/heavy-CPU, sustained churn, real kernel swap and
physical-media qualification remain open. Steps 1/2 have their standard RAM
qualification; Steps 3/4/5 (asynchronous TRIM, churn/WAF, map compaction) remain
outstanding. Alpha.27 is one reviewed cache follow-up before Step 3.

## Deferred optimization evidence gates

- **ID38 K>1:** keep passive counters. No second write slot is justified.
- **ID39 helper concurrency:** refuted and removed from current source. Do not
  restore a helper workqueue merely to satisfy historical telemetry.
- **ID60 same-extent grouping:** refuted and retired. Do not keep a dedicated
  loaded A/B after the code path is removed; ordinary reads already use the
  shared extent/metadata caches.
- **ID63 adjacent READ coalescing:** production keeps `read_coalesce=1` by
  default. Retain five matched fast rounds and five matched serial-depth rounds.
  The latest successful matrix reconfirms fast sequential request reduction
  without a statistically established throughput/p99 loss and strong serial
  request/throughput/p99 wins; exact-current-main confirmation remains required
  after alpha.27's cache change. Every merge remains exact, same-segment,
  <=8 blocks total and zero-padding; `parallel_read_coalesce_extra_blocks`
  stays zero and defensive skip-other stays zero. Eligibility must use shared
  cache metadata without private-slot memcpy, and source contracts must prove
  successful upper BIO completion precedes shared LRU absorption.
- **ID64 one-shot in-flight-zero shrink guard:** retired. Do not restore the module parameter, shrink helper or loaded A/B. Compatibility status fields stay zero so existing report parsers remain stable.
- **K=1 shallow detach gate:** fast QD4/QD8/QD32 require five matched sync/async pairs. Acceptance requires the prior QD4 regression to disappear, QD8/QD32 to keep statistically positive async gains, and fast mixed lower request inflation to improve without useful-throughput or read-tail loss.
- **K=1 read-bypass detach attribution:** `pipeline_read_bypass_skips` counts a window only when every asynchronous-detach predicate except the existing read-bypass guard is satisfied. It is passive evidence, not a policy change. Do not infer this count from serviced READs, PACK_READY service-dry closes or rounded run-slot occupancy; use the exact counter before proposing a controlled guard A/B. Any new timed write-status counter required by report qualification must also be carried through the replay snapshot/delta schema and covered by a nonzero replay regression, so missing telemetry cannot be mistaken for a benchmark failure.
- **Device-model limits:** every report must distinguish the configured null_blk MiB/s cap from the analytical unmerged-4KiB latency ceiling (4096 * hw_queue_depth / completion_nsec). The console must show both in decimal MB/s and must not call the calculation a measured bulk calibration.
- **ID65 synchronous read cleanup:** owner-qualified. Any non-ID63 candidate
  must now return before slot preparation/priming; no standalone same-extent
  slot execution remains. Fast/serial ID63 retain five-pair confirmation.
- **ID66 discard scratch cleanup:** owner-qualified. Source/native contracts
  continue proving the temporary live-reference decrement is exactly restored
  before return/commit, including an error after a validated shared-extent page.
- **ID67 predictive rescue:** rescue remains default-off. RAW or >2024-byte LZ4
  baselines use threshold 24 and require a strictly smaller candidate. A
  baseline at or below 2024 bytes is eligible only when the production planner
  identifies the exact next uniform SWZ packing limit; that route uses threshold
  16 and the candidate must cross the packing cliff as well as remain strictly
  smaller. Default-off qualification is not promotion evidence: enabling rescue
  requires representative positive content and a controlled loaded on/off A/B.
  The official rootless stage must build/run the native evaluator, emit exactly
  one sanitized
  `SWAPZ_PREDICTOR_EVIDENCE` record, and fail if it is missing or malformed.
  SHAKE entropy/mixed/medium plus generated zero/repeat pages are negative
  controls; deterministic pointer/page-table/integer/float/struct and
  independently based 512-byte regions are positive controls. The classifier's
  eight-pair first stage rotates across all four 128-byte lanes and eight
  16-byte phases; deterministic repeated-header and lane-specific signal
  controls must catch regressions in those sample positions. The native evaluator
  shares production eligibility, threshold and packing-cliff helpers and reports
  the exact hybrid route separately from threshold sweeps. These native controls
  qualify route behavior, not loaded performance. Delta64 is the
  sole maintained predictor. The classifier is always scalar C. Qualification
  compares scalar/SSE2/AVX2 (or scalar/NEON) full-page transform and inverse
  implementations byte-for-byte, batch-times them independently on the same
  host, and verifies exact inverse reconstruction. The emitted evidence line
  must remain one parseable JSON object with backend timing preceding threshold
  rows; malformed evidence fails the official runner even when the C binary
  itself exits zero.
  The rescue signpost ignores zero residuals, aborts after the 8-pair first
  stage below score two, and extends passing pages to 32 strided pairs. A prior
  fixed-phase first stage could miss structured pages with repeated headers;
  historical zero-call loaded counters from that classifier are not reliable
  evidence that representative pages lack delta64 structure. Keep the default
  off pending a rescue-on/off loaded A/B using the corrected sampler and
  representative page content.
  Classifier ns/page uses repeated batched sweeps. Every threshold reports
  per-negative-profile false calls, classifier-routed planner block/extent
  savings, routed extra CPU ns/corpus-page and ns/saved-block. CPU accounting
  charges every eligible page one classifier cost and every routed call one
  selected-transform plus second-LZ4 cost; compare against 390625 ns per 4KiB
  for SD_EMULATED and 48828 ns for SSD_EMULATED. Source contracts prove
  static-call kernel dispatch,
  x86 AVX2 CPU+YMM-state gating, SSE2 compatibility fallback, arm64 kernel-mode
  NEON gating and isolated FPU compiler flags. On x86_64 the rootless build must
  also disassemble the isolated native objects and prove SSE2 `psubq/paddq` and
  AVX2 `vpsubq/vpaddq` code generation from materialized disassembly files;
  do not pipe `objdump` into an early-exiting `grep -q` under `pipefail`,
  because the resulting SIGPIPE is a false qualification failure. Source-level
  vector syntax alone is insufficient acceleration evidence. Native evidence
  must report selected-backend and scalar-C timings on the same host for the
  classifier, forward transform and inverse transform before changing dispatch
  policy. The unprivileged Make-interface fixture must emit the same valid
  evidence schema and must resolve the nearest non-report source SHA exactly as
  the outer runner does. Production qualification additionally requires an
  explicit SWZ per-record delta64 flag, byte-exact LZ4+inverse reconstruction,
  strict candidate-smaller-than-baseline admission, map/metadata encoding
  cross-checks, and GC relocation that preserves the stored encoding.
- **ID58/59:** representative-content evidence only.
- **ID61:** the owned-RAM lifecycle phase now collects foreground-GC pressure
  evidence before any background worker. Exactly five pressure rounds must emit
  useful-WRITE wall/p99; loaded status must show positive total GC wall and
  victim-choice wall plus exact map/segment/relocation scan counts. Incremental
  victim accounting must keep `gc_choose_map_entries == 0`; relocation-map
  scans remain observational. The report
  records round-0 baseline p99, maximum later-round p99, GC wall as a
  fraction of useful-WRITE wall, and the existing no-headroom skip count. This
  is observational only: no GC worker,
  victim-policy change or reverse index is permitted in the evidence commit.
- **ID62:** current host-safety rules still prohibit physical-device
  collection; this cleanup does not authorize real storage.

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
collector. Higher lower-I/O depth is a later explicit K experiment. Generic
ordinary-LZ4 preparation concurrency remains blocked by the prior shallow-backlog
evidence. The separate delta64 K=2/K=4 pilot is permitted because rescue adds an
independent transform plus second LZ4 pass; it must prove timed lane overlap on
the deterministic positive fixture before any broader concurrency claim.

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


The canonical report is the single root file `test_results.json`, written as
UTF-8 JSON with newlines and no indentation so connected readers can inspect it
directly. Formatting keeps the complete current matrix below the reader's
size limit without dropping any telemetry.
The runner keeps it unchanged while qualification is executing so loaded safety
checks still see a clean tested tree. At the end of every completed PASS, FAIL,
or BLOCKED run it atomically replaces that file with the sanitized stage,
failure-phase/diagnostic, lifecycle and benchmark result for the exact
`tested_commit_sha`.

After writing the file, `make test` automatically publishes only that report
to `main` using Git plumbing. `tested_commit_sha` names the nearest
non-report code revision; generated report-only ancestors modify only
`test_results.json` and do not become new code revisions. Source revision
normalization has no fixed report-chain depth, so repeated qualifications of
unchanged code cannot eventually turn a report-only commit into tested source.
The report is built on the actual current main head so report-on-report updates
remain normal fast-forwards. Transient push/fetch failures receive a bounded
exponential backoff retry. A moved main head is accepted only when the exact
tested source remains its ancestor. Divergence, force-push, report branches/PRs,
and replacing newer source bytes remain forbidden.


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
`WQ_MEM_RECLAIM | WQ_UNBOUND`. The ordered authority workqueue remains
single-active. Preparation remains one lane unless both async preparation and
delta64 rescue are enabled; the read-only
`delta64_prepare_workers=1|2|4` diagnostic parameter may then raise only
preparation concurrency. The default loaded qualification uses K=1 and K=2
only; K=4 is retained solely for explicit diagnostics after two directional
four-CPU observations regressed throughput. Every lane must own private
input/predictor/LZ4 scratch and single-writer diagnostics, while the existing
64-page prepared-payload mask is shared and bounded. Bound/affinity-pinned
preparation remains rejected. FIFO admission, global packing, physical WRITE
submission, authority publication and BIO completion remain serialized under
the ordered owner. Every K=2 qualification observation must report timed
overlap; every K=1 observation must report none. Rootless/report fixtures must
carry the same five counterbalanced K=1/K=2 pairs so parser and fail-closed
evidence gates remain covered without privileged module loading.
Synthetic delta64-positive records must keep score-band totals exactly equal to
eligible pages; mocks may not bypass the production accounting invariants. The
current positive control starts from an accepted >2024-byte LZ4 baseline, so
mocked adoptions are LZ4 rescues and its sub-2024 packing-cliff counters remain
zero.

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


Nonblocking preparation-slot qualification executes the shared production
mask helper with C11 atomic shims. Exercise all 64 slots, exhaustion without
mask mutation, bit 63, release/reclaim, rejected-claim cleanup and concurrent
producer/consumer payload reuse. Native stress does not prove the Linux memory
model or loaded BIO lifecycle. Source contracts require a bounded claim before
`queue_lock`/descriptor removal, no producer allocation or semaphore, return on
all three early-release paths, pointer clearing before bit return, release
barrier plus ordered compare/exchange, array destruction after worker drain,
and an all-free mask in the suspend/drain invariant. The owner matrix must
still cover byte-exact reads, deep-QD reuse, faults and suspend/teardown.
Require 64-byte element alignment/stride and a cheap queue-count hint before
claiming, followed by the authoritative locked queue check. Source contracts
must require a final producer drain after the ordered queue drain and before
the free-mask invariant. An early producer drain alone cannot exclude work
queued by an ordered callback still running. Native mask stress does not
exercise this workqueue lifecycle; loaded suspend/teardown remains required.


### Lower-WRITE queue starvation and GC distribution attribution

Low-depth asynchronous-preparation qualification must prove the idle producer
gate in source: four unclaimed tails are required for an idle tail-credit wake,
the pre-head wave starter requires five total queued preparations, and an idle
producer tail claim requires two queued descriptors. Active lower WRITE overlap
is exempt and may wake on one queued descriptor. No new status fields are
required. Owner evidence must re-run the existing persistent-worker QD1/4/8/32
matrix; the candidate is rejected if QD8/QD32 loses its confirmed advantage or
if QD1/QD4 still pay material producer-wakeup cost.

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
segments. This establishes synthetic reuse-distribution evidence; it is not a physical
wear claim. ID29 now uses it as the prerequisite for bounded owned-RAM
whole-dead-segment DISCARD. The lifecycle device must explicitly expose discard
support; reports retain completed segment-discard count/sectors and reject
misaligned, unsupported or failed discard evidence on that owned test device.

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

A separate `ls-remote` authorization probe is not required. Report commits
are pushed normally (never force-pushed) on the actual current main head, which
may itself be report-only. After a failed push, bounded retry backs off and
retries transient fetch/push failures even when origin/main did not move. If it
did move, `merge-base --is-ancestor` must prove the tested code revision
remains in current main history before a report-only child of that fetched head
is attempted. Rewritten/diverged history or exhausted retries fail closed.

### Generated report versus tracked source cleanliness

`test_results.json` is the one generated overwriteable evidence file and is
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


### Foreground GC pressure evidence

The existing `--gc-stress 5` owned-null_blk phase is the ID61 pressure oracle.
It must retain byte-exact verification of all 4096 logical pages and the existing
victim/rotation/TRIM requirements. Each round emits exactly one
`GC_PRESSURE_ROUND` record containing successful WRITE count, summed WRITE
wall, WRITE p99 and final fsync wall. Loaded qualification emits one
`PASS_LOADED_GC_PRESSURE` record with five rounds, positive useful-WRITE wall,
baseline/pressure p99, total GC wall, GC-wall fraction, victim-choice wall/calls,
the existing no-headroom skip count, and exact choose-map, choose-segment and
relocation-map scan counts.

For the current 4096-page oracle, choose/relocation map-entry deltas must be at
least `gc_victims * 4096`; this proves the full-map scaling cost is actually
being exercised. The public `swapz_gc_compact_one()` wrapper owns only complete
attempt wall attribution; source contracts for victim choice, relocation,
rotation, trim and GC lower-I/O accounting inspect
`swapz_gc_compact_one_inner()` so timing instrumentation cannot weaken those
existing invariants. The parser recomputes the integer GC-wall fraction and
rejects missing/inconsistent evidence. Native report and Make-interface fixtures
mirror the complete marker. No acceptance threshold for “background GC is
useful” is hardcoded: the owner evidence first determines whether GC wall/tail
impact is large enough to justify another architecture experiment.

### Native Make-interface benchmark fixture fidelity

The unprivileged Make-interface qualification may replace the privileged loaded
stage with deterministic synthetic output, but that fixture must mirror every
field that the real report parser treats as benchmark-model identity. When
lower queue geometry is part of the model contract, fake
`PASS_RAM_MODEL_LOWER_MBPS` records must include the exact queue mode,
submission-queue count and hardware queue depth for each regime. A parser
schema change must update this fixture in the same change so rootless
qualification cannot pass evidence that a real loaded run would reject.
ID69 is no longer a dual-mode benchmark policy. Native/Make-interface loaded
fixtures must instead mirror the canonical packed-placement invariants consumed
by the lifecycle parser: aggregate placement waste equals segment-tail waste,
hole-induced run splits are zero, and the byte-exact placement smoke reports
zero holes and zero splits. Retired aligned-mode A/B markers must not reappear.


The write-only saturation parser consumes the same exact owned-RAM device-model
identity as the mixed benchmark parser. It must validate queue mode,
submission-queue count and hardware queue depth in addition to bandwidth,
completion delay and IRQ mode, and it must reject any arm whose replay mode is
not `persistent-write`; a private pilot may not silently accept a different
lower queue geometry or the retired wave dispatcher.


### Report-contract fixture model identity

Native report-contract fixtures must emit the complete configured storage-model
identity accepted by the production parser. Mixed and write-only synthetic logs
therefore carry queue mode, submission-queue count and hardware queue depth as
well as bandwidth, completion delay and IRQ mode, and their expected
`device_model` dictionaries compare all six fields.


### Timed scheduling attribution

The loaded replay snapshots all window-size bins, close reasons, one-page close
reasons, deadline contexts, retained-burst counters, preparation counters and GC
victim count immediately before releasing the first measured wave or
persistent-worker start gate and after the required measured final fsync.
Reported mixed and write-only scheduling tables use only
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

ID57 production intervention counters are removed with the rollback. Rootless and
source contracts instead require the old ID56 observational tail sampler,
absence of K=1-busy PACK_READY suppression/zero-tail hold state, and the new
passive ID38 ready-wait accounting described above. The owner run must verify
that fast write-only QD8 returns toward the pre-ID57 target-8/no-deadline
geometry and that fast mixed service-dry/request fragmentation does not remain.

The next passive shrink-attribution counters do not alter ID56/ID57 policy.
Every actual `burst_target_shrinks` event is assigned exactly once to
after-inflight-zero, after-read-bypass or other, and independently to <=8,
9..32 or >32. Both sums must equal `burst_target_shrinks`. The remembered
in-flight-zero flag is cleared by a nonzero tail sample or a truly quiescent
hard boundary; it must not suppress PACK_READY, defer sampling, or change the
target.

ID24 boundary CPU attribution is measurement only and is not a trustworthy
total for short callbacks. Status/timed deltas retain
`ordered_worker_cpu_ns` and `prep_worker_cpu_ns` as scheduler-accounted
lower bounds. The retired ID39 compatibility field `read_worker_cpu_ns` must
remain zero; source contracts assert that no read-helper callback or CPU
accumulator survives. Reports must also expose separate `ordered_lz4_wall_ns`,
`prep_lz4_wall_ns`, `ordered_write_copy_wall_ns` and
`prep_write_copy_wall_ns`. The report shows
callback wall, scheduler lower bound and measured non-sleeping phase floors
separately. No worker-count/affinity conclusion may rely on the boundary
`sum_exec_runtime` value alone.

### Synchronous grouped-READ qualification

The fast directional `parallel_reads=0/1` control remains a single off/on
observation with `read_coalesce=0`. It now measures grouping-regression
behavior only; it is not a Kread concurrency experiment. Both arms must report
`parallel_reads_enabled=0` and `read_worker_cpu_ns=0`. The off arm must
report zero grouped pairs; the on arm must exercise same-extent grouping before
the control is accepted.

ID63 is the promoted request-efficiency mechanism. The loaded test therefore
keeps exactly ten SSD_EMULATED and ten SD_EMULATED ID63 sessions in the fixed
counterbalanced confirmation sequence while varying only `read_coalesce=0/1`.
Every pass remains 4 MiB/1024 byte-exact verified pages. Report paired p99,
useful-throughput, lower-byte and lower-request changes with two-sided
Student-t 95% confidence intervals.

No `swapz-read` workqueue, per-slot work/completion object, helper
`queue_work`, `wait_for_completion` or `flush_work` is permitted. A
non-coalescible distinct-extent pair must return from grouped-batch selection
without taking BIO ownership. Same-extent siblings and exact ID63 pairs run
synchronously on the ordered worker; shared cache mutation and BIO completion
remain single-owner.

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

Rootless console-report coverage must pass the parsed directional grouping
object to the printer; a display assertion is not valid against a report that
omits the evidence object entirely.

The unprivileged Make-interface fixture must mirror the current telemetry
schema and emit the ID64 directional marker pair, fast/slow ID63 confirmations,
and the directional grouping/ID60 controls. A fake loaded stage is not allowed to
bypass new fail-closed fields merely to exercise incremental Make behavior;
fixture records use the same parser and conservation contracts as owner-loaded
output.


### Native GC map-scan scaling evidence

The rootless stage must run a bounded native GC scaling microbenchmark at
262,144 and 1,048,576 logical pages (1GiB and 4GiB at 4KiB/page). It reports
four CPU-only timings: the retired full-map score rebuild, current per-segment
victim selection, legacy full-map relocation ownership discovery, and ID61b
per-segment-list relocation of the same 256 survivors. The sanitized report
must retain both geometry rows. Timing is directional CPU evidence, not a
physical-media latency claim. Loaded qualification must additionally prove that
successful GC visits exactly `gc_pages` relocation-list entries, rather than
merely timing a native surrogate. Report `85aeac4` satisfies this production
gate with 20 relocation-list visits for 20 relocated pages,
`gc_choose_map_entries=0`, 20 victim rotations and byte-exact verification of
all 4,096 logical pages. Keep the full-map relocation path only as the portable
fallback when the segment-membership sidecar is absent.


### Placement/reclaim qualification

Owner qualification records foreground and GC placement-waste blocks,
including aggregate holes and separately reported segment-tail waste,
lower-run splits attributable to intra-segment holes, dead-segment probe
segments/full scans and probe wall time, duplicate successful-DISCARD skips,
and logical segment-open min/mean/max.

Owner report b0623ae0 qualified the post-promotion ID69 matrix with five matched
pairs on each maintained owned-RAM model. Packed placement reduced physical
WRITE requests by 15.0% (paired CI [-19.4%,-10.6%]) on the serial
model and 13.3% ([-18.8%,-7.8%]) on the fast model, while consumed blocks fell by 24.4 and 29.8
respectively; every packed arm had zero internal holes/splits, zero GC
contamination and unchanged logical segment opens. That evidence retires the
aligned policy and its A/B harness.

The production qualification is now structural and fail-closed: the canonical
1/2/4-block allocator must place extents back-to-back within a segment;
`alignment_hole_blocks_foreground == segment_tail_waste_blocks_foreground`
and the corresponding GC counters must also be equal; `run_splits_by_hole`
must remain zero; and the separate byte-exact packed-placement smoke must report
zero holes, zero splits and no failure. Segment-tail waste at a real 1MiB
boundary remains valid and continues to be counted in the aggregate hole
counters. The fixed `packed_placement=1` status token is compatibility
telemetry, not a runtime policy. None of this changes SWZ.

Exact production-C authority coverage also exercises append-only packed
placement at segment edges: two blocks at cursor 254 and four blocks at cursor
252 fit with no waste; two blocks at 255 and four blocks at 254 skip only the
unusable tail and increment aggregate and tail counters equally. If the skipped
extent would enter the reserve, staging returns `-ENOSPC` without changing the
cursor, in-flight state or counters. Randomized native assertion markers must
retain the safe test source and line so the sanitized report identifies the
failing check without publishing host paths.

Native GC scale evidence compares the previous per-probed-segment 256-entry
dead-segment scan with mapped-page fast rejection at 262,144 and 1,048,576
logical pages. Loaded qualification still requires the full zero-mapped
candidate liveness scan, repeated live-GC correctness, exact readback, and
nonfatal DISCARD semantics.

Logical segment-open spread is allocator telemetry, not flash-wear evidence.
The production least-opened-segment switch remains default-off and the official
loaded harness currently requires `logical_open_balance=0`; native semantics
alone do not qualify promotion. The latest qualified baseline reports
1/1.25/2 min/mean/max opens across 64 segments and 80 total opens, already the
best possible integer min/max spread for that workload. A future loaded A/B
must therefore use deliberately skewed churn and compare spread, allocator
probe count/wall time, GC work, lower I/O, useful throughput and p99 while
varying only this policy. No threshold from RAM-backed `null_blk` may turn
that counter into a NAND-wear claim or promote cold-data relocation.


ID70c loaded qualification uses only the owned RAM null_blk mapping. It must
prove that an upper DISCARD which removes the final mapping from a closed
1MiB segment immediately completes exactly one 1MiB lower DISCARD, and that
later allocator reuse increments the already-trimmed skip counter while
byte-exact verification still passes. This is synchronous ordered-worker
reclaim, not background TRIM and not physical-media endurance evidence.

ID73 is native simulation evidence only. The deterministic study must compare
aligned 1/2/4, packed 1/2/4, packed exact 1/2/3/4, packed up-to-32KiB and
packed up-to-64KiB geometries and report blocks, placement waste, write runs,
cold-read blocks and sequential 4MiB request estimates. Candidate 3/8/16-block
classes in this table do not exist in kernel policy or SWZ.

### Delta64 SIMD qualification

Every compiled delta64 SIMD backend must round-trip and produce a transform
byte-for-byte identical to scalar C before timing is reported. Rootless x86
qualification disassembles the architecture objects to prove vector arithmetic
is present without executing unsupported instructions. Runtime benchmarking
executes AVX2 or AVX-512 only when the host CPU advertises the corresponding
feature. Backend timings are evidence, not an automatic policy gate: a new
wider backend requires same-host results before any inverse-policy promotion,
and official qualification on a host lacking that ISA does not qualify its
runtime path.

### Core-2 two-choice metadata cache and copy avoidance

The metadata cache keeps exactly 512 immutable SWZ block-zero images, but its
directory is 128 sets by four ways. Each tag is exactly 16 bytes and each
four-way set starts on a 64-byte boundary. Each key has two distinct hashed
set choices. Search primary first and inspect secondary only after a primary
miss: at most two tag lines/eight tags. A 512-entry fallback scan or separate
direct front is not permitted. Replacement chooses an invalid way before the
oldest tag across the two candidate sets. Complete invalidation before authority mutation remains
mandatory, but normal mutation invalidation advances a directory epoch rather
than clearing 512 validity entries. Epoch wrap may clear the directory before
starting a new nonzero epoch.
A cold zero-epoch lookup still performs the bounded eight-tag probe for stable
telemetry, but zero epoch can never validate a tag as a hit.

Directory commit must deduplicate keys even when scratch/extent-cache hits
skip directory lookup. Scan both sets for an existing key before using
an invalid/oldest slot; a hole before a match must not hide that match.
Refresh age without inserting, copying the block, or counting replacement.
Exact production-C coverage creates four distinct colliding extents, repeats
their sibling reads, and requires one tag per key, no replacements, exact
payloads and each physical extent block fetched only once. The seven-record,
2072-byte fixture appends payloads backward: the initial record-zero read warms
metadata block 0 plus payload block 3, so the sibling sweep must fetch only
blocks 1 and 2 for each extent. Test a hole before a match as well. These checks
prevent duplicate self-eviction. Additional native coverage places nine keys
that collide under the primary hash across primary and secondary ways, revisits
them with exact payload checks and no extra metadata reads, and verifies four
primary plus five secondary hits. A scratch hit with an invalid primary way
must retain its existing secondary tag. Fill all candidate ways and prove the
oldest secondary candidate wins over a newer primary candidate; an even older
noncandidate must remain untouched. Exercise epoch and age-clock wrap, as well
as transfer/reset of both hit counters from private engines.

An ordinary metadata-cache hit parses and sequence-checks the cached block
directly. It must not copy all 4096 bytes into read scratch merely to decode one
record. If the selected payload overlaps block zero, copy only that exact
payload fragment; CRC validation must cover the reconstructed contiguous payload
and remain bound to the separately validated metadata/authority identity.
A separately cached block zero must never be advertised as direct/extent
read-scratch residency unless all 4096 bytes are actually present there.

Loaded qualification must report metadata lookups, total/primary/secondary hits,
probes, two-choice replacements and cached-block payload-copy bytes. Require
primary + secondary = hits <= lookups, at most eight probes per lookup, and
the tighter total-probe bounds implied by 1..4 for a primary hit, 5..8 for a
secondary hit and exactly eight for a miss. Missing counters are unavailable
evidence. The replay and report validators both reject impossible accounting.
Native coverage must additionally prove
sizeof(tag)==16, four adjacent ways occupy exactly 64 bytes, the tag directory
starts on a 64-byte boundary, mutation advances the metadata epoch, and a second
already-empty invalidation does not churn the epoch. Source-contract extraction
must recognize the secondary hash's actual `swapz_u16` return type. A narrow
parser regression extracts a multiline definition after its prototype, so an
unsupported return type cannot be mistaken for a missing production helper.
Retain the assertions on the real hash body and distinct secondary set.
Compare the owner run
against source 5bdd040334ee's baseline rather than inferring a win from source
structure alone. The unprivileged Make-interface fixture must emit all seven
locality fields with internally consistent bounds so rootless qualification
cannot bypass the loaded telemetry schema. Native replay fixtures must initialize
these counters by field name rather than positional tuple order; adding telemetry
must not silently shift unrelated coalescing or worker counters.

No lower-I/O, cache-capacity, generation, CRC, selective-read or coalescing rule
changes in this round. Predictor qualification continues to require SSE2
transformed bytes and inverse reconstruction to match scalar exactly.

### Production delta64 qualification

The delta64 transform unit is one 4KiB logical page, never a whole packed
extent. Direct production-C coverage must prove ordinary LZ4 and delta64 records
share the unchanged 16-byte SWZ record size, decode the encoding bit exactly,
reject reserved header flags, and preserve payload CRC validation.

Both write owners must bypass rescue when the read-only, default-off
`delta64_rescue` module parameter is disabled. Snapshot it at construction and
allocate predictor scratch only when enabled. The bare-load smoke and reload
must assert `delta64_rescue=0`; all rescue counters and wall time stay zero.
This describes the bypass, not classifier selectivity. Encoded reads retain
inverse support and fail closed if their scratch is missing.

The inherited opt-in classifier has two paths. RAW or >2024-byte LZ4 baselines
keep threshold 24 and require a strictly smaller delta64 candidate. For an
already-compressed baseline at or below 2024 bytes, the engine computes the
next exact uniform-payload packing limit across 4/8/16KiB SWZ extents. Pages
with such a lower limit may use threshold 16, but adoption also requires
crossing that packing limit. Neither path runs while rescue is disabled.
Source `9a802eff7d9d` is owner-qualified with rescue off and fixed-array
preparation. Packing-aware rescue-on behavior still lacks loaded qualification;
native structured pages remain opportunity evidence. Console legends must
describe both eligibility paths, thresholds 24/16, all score bands and the
uniform-cliff limit. Shared production-route screening evidence must be split
across compact Markdown tables so every rendered console line remains below 96
characters. Metadata payload-copy counters exclude cache insertion copies and
directory lookup counts exclude scratch/extent-cache hits.

Capture every production `delta64_*` counter in drained, timed mixed and
sustained-write snapshots. Missing fields are unavailable evidence, not zero
activity. Require adopted <= attempts <= classifier passes <= eligible; the four
score bins 0-7, 8-15, 16-23 and 24+ must sum exactly to eligible; 24+ scores are
a subset of classifier passes; packing-adopted <= packing-cliff-crossings <=
attempts; packing-adopted <= packing-attempts <= packing-eligible <= eligible;
packing-adopted <= LZ4 rescues; adopted = RAW rescues + LZ4 rescues; and
total/split payload-byte savings must match. Reject resets and impossible
per-rescue savings.

The replay records `delta64_rescue` as a required policy gauge, not a counter
delta. The snapshot source contract must require both this gauge and the retained
burst target, plus the unchanged-policy, boolean-value and disabled-activity
guards; it must not pin the retired one-gauge tuple.
Reject changed/nonboolean policy or any disabled-target rescue activity.
Rootless fixtures distinguish enabled-positive, enabled-negative and
disabled-zero cases. Print the policy with a legend and interpretation so a
bypass cannot be presented as evidence of classifier selectivity. Payload-byte
savings do not establish lower I/O savings or a speedup. A causal comparison
requires identical source/workload, one controlled toggle, comparable host
load, independent lower I/O, useful throughput, p99 and worker CPU. Keep K=1
and per-record encoding unchanged and collect representative content plus a
positive loaded control before reconsidering the default.


The console prints mixed-arm general attempts, packing-path activity, score
distribution and payload savings. Zero packing adoptions mean the new
integration created no loaded packing evidence. Nonzero packing adoptions prove
that adopted sub-2024 candidates crossed a uniform SWZ geometry boundary, but
actual lower-I/O savings still require loaded physical WRITE bytes/requests or
packing geometry to improve. Native planner coverage must include the exact
1803 -> 1802-byte nine-record case: five blocks/five one-block extents before the crossing (the existing
lower-read tie-break) and four blocks/one extent after it. Native corpus tables stay separately
labeled and cannot substitute for production counters.

Counter attribution does not by itself establish a causal A/B for delta64 or
the metadata directory. The owner comparison must retain independent lower I/O,
useful throughput, p99 and worker CPU evidence. For this round the explicit
acceptance goal is narrower: preserve correctness and read tails, reduce
metadata-directory/copy work on the Core-2 host, and show either actual lower
WRITE bytes/requests or stronger packed-extent geometry when packing-path
delta64 adoptions occur. If packing-adopted remains zero, use the score bands to
choose the next classifier experiment rather than lowering the threshold
blindly.

### Unversioned SWZ format identity

Until an incompatible deployed format boundary is justified, maintained source,
tests, workflows and documentation call the on-disk format `SWZ` only. Rootless
source qualification rejects the retired generation-suffixed format name. The
codec keeps the unversioned `SWZ\\0` magic and requires reserved header flags
to remain zero; a future incompatible format change must introduce its identity
deliberately rather than pre-versioning an undeployed format.

## ID73 CPU/cache qualification

`make test -jN` remains the only public qualification entry point. The native
predictor stage must additionally verify x86 SSE2 object code contains
`shufpd` and `pslldq`; byte-exact scalar/SIMD round-trip tests remain
authoritative for semantics. Do not impose a cross-host nanosecond threshold on
CI.

The same deterministic entropy/mixed/medium plus structured corpus must run an
ordinary-LZ4 acceleration sweep at 1, 2, 3 and 4. For every accepted compressed
page, decompress and compare all 4096 bytes. Acceleration 1 must reproduce the
existing baseline length exactly. For each setting report ns/page, accepted
payload bytes, raw fallbacks, and physical blocks/extents from
`swapz_engine_plan_bounded()`. A faster compressor is not a promotion unless
loaded matched evidence also preserves or improves lower WRITE bytes/requests,
throughput and tails.

The loaded LZ4 acceleration family is a five-pair, counterbalanced SSD-model
A/B between settings 1 and 4. Keep `async_prepare=1`,
`delta64_rescue=0`, workload, fixture, trace and RAM-device geometry fixed;
alternate raw/swapz replay order. Require terminal markers, exact
source/fixture/trace provenance across all ten sessions, valid host CPU/PSI,
and nonzero total/ordered/preparation LZ4 timing. Report paired 95% confidence
intervals for useful WRITE rate, p99, lower WRITE bytes/requests, LZ4 timing,
raw-control throughput drift and host-load deltas. The parser must close the
mixed session before this family starts and keep the A/B out of mixed-matrix
and sustained-QD results. Intermediate acceleration 2/3 remain covered by the
native round-trip/geometry sweep; standard loaded families use acceleration 1
with delta64 disabled.

Source-contract qualification must pin the safety boundaries of the optimized
paths: generic-planner duplicate protection remains enabled; only the
prevalidated production planner sets the uniqueness fast flag; cached metadata
uses descriptor-only lookup only behind a validated-source test; metadata
sequence is checked before payload lower I/O; provisional coalesced blocks
cannot be published as validated cache; publication preflight contains no
global GC mutate/restore loop; and paused-batch hashing covers the active
transaction prefix.

Loaded drained status snapshots must include `lz4_acceleration`,
`delta64_transform_calls`, `delta64_transform_wall_ns`, and the passive
`parallel_read_adjacent_chain_3plus`,
`parallel_read_adjacent_chain_extent_max`, and
`parallel_read_adjacent_chain_blocks_max` fields. When delta64 is enabled,
transform calls must be bounded by candidate attempts and transform wall must
be nonzero if calls are nonzero. Compare wrapper-inclusive production
transform ns/call with the raw native backend value; the difference is part of
the rescue economics.

The active ID63 protocol accepts two through eight extents only when every
constituent belongs to the already-admitted independent READ prefix and the
exact missing ranges form one same-segment, zero-padding span of at most eight
blocks. Native coverage must prove at least a three-range success, gap and
segment rejection, lower-read failure, and constituent payload-CRC failure;
the existing pair cases remain compatibility coverage. Loaded merge-on/off
qualification must keep byte-exact reconstruction and zero extra blocks, allow
`parallel_read_coalesced_reqs_saved` from one through seven per combined
batch, and report lower requests, useful throughput and p99. The conservative
3+ full-extent counters remain opportunity evidence, not proof of an active
merge.

Publication tests must continue to inject malformed siblings and GC-accounting
underflow/overflow and prove all authority arrays are byte-for-byte unchanged
on failure. Successful multi-record publication must prove live-record,
mapped-page, GC-score and page-list totals equal a slow recomputation after the
aggregate fast path.
