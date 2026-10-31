# Testing Standards

**Immutable naming policy (read before every prompt):** The project is `swapz`; the kernel module is `dm-swapz.ko` (loaded as `dm_swapz`); the Device Mapper target is exactly `swapz`; and the module alias is `dm-swapz`. Never put implementation-generation numbers in product, module, target, source-path, report, workflow, helper, or schema names. `SWZ` is the current unversioned on-disk format identity; do not assign a format version until an incompatible format boundary is justified.

**Single official test command (read before every prompt):** Run `make test` at the repository root for every supported swapz test and benchmark. A complete run must report BLOCKED (nonzero) if safe noninteractive privileged qualification cannot run. Do not create, publish, recommend, or document alternative test commands; the sole owner-approved exception is the development decision loop `make fast_test`, which never qualifies a source, never writes or publishes `test_results.json` and never replaces `make test`. Private scripts and CI jobs are implementation details, not operator interfaces.

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

### Development decision loop

The project-goal CI policy validates all five root Make targets
(`all install uninstall test fast_test`). This does not make `fast_test` a
second public qualification command: `make test` remains the sole official
qualification entrypoint.

`make fast_test` is the owner-approved development loop, not a qualification
command. It builds the current working tree (dirty trees allowed), runs the
lower-I/O window-policy native checks, runs the root preflight, and then runs
one counterbalance-free raw/swapz pair per selected scenario through the same
private owned null_blk pair helper and exact device models used by `make test`
(default: three repeats each of SATA mixed, NVMe Gen4 mixed, fast mixed,
fast QD4 and fast QD8). A selected `nvme5-stripes` or `sata-stripes`
scenario instead runs the separate multi-target N=1/2/4 decision experiment
described below. It prints one table of useful READ/WRITE, lower WRITE bytes ratio
and requests, READ/WRITE p99, windows, deadline and idle-bound closes,
accepted-work lower idle, lower-WRITE service and its EWMA, and keeps detailed
telemetry in `build/tests/fast-test/latest.json`. `SCENARIOS=` and `REPEAT=`
select scenarios and repeats; `DELTA64=0` pins the LZ4-only control policy. It never writes or publishes `test_results.json`,
never records a qualification verdict and never substitutes for `make test`:
single unpaired observations decide only which candidate deserves the full
owner matrix.

`CONTENT=medium` keeps the existing fixture. `CONTENT=entropy` supplies only
incompressible pages; `CONTENT=balanced` supplies equal numbers of medium and
entropy pages. These are synthetic content controls, not representative swap
populations. Each private pair loads the kernel LZ4 dependency before inserting
the product module, including the first development pair after a boot. Keep the selected content and the actual fixture metadata (weights,
page counts, measured LZ4 sizes and hash) in the development JSON, alongside the
immutable plan hashes consumed by both arms. A private helper's medium protocol
selects queue geometry; the shared fixture remains the content authority. Never
attribute a content change to a source optimization or mix these controls into
the qualified medium history.
An all-RAW shared fixture omits the separate compressed-pack population/readback
phase because it has no compressed pack to qualify; mixed replay and complete
image verification remain mandatory. The omitted phase is explicit in the
pair log and JSON (`packed_read=null`). Official medium/delta-positive pack
requirements remain unchanged.

Mixed development scenarios ending in `-mixed-lanes` use persistent native
lanes; `-mixed-lanes-waves` is their matched wave-barrier control. The ordinary
`-mixed` scenarios and the owner qualification matrix retain their original
wave trace. The two new plans must have identical operation, payload and final-
image hashes, with per-lane WRITE stripes and an immutable disjoint READ region.
Only start/end phase barriers are allowed in the persistent mode. Both modes
retain byte-exact timed READs and complete final-image verification. Results
must identify the replay mode and remain outside the existing history series.
This is workload sensitivity, not a production-source performance A/B; actual
reclaim can be bursty too. Keep new traces out of the qualification matrix until
separately justified.

The development loop automatically screens host noise with the replay's existing
`/proc/stat` and CPU-PSI counter readers. It samples 200ms quiet windows before
and after each owned pair, outside useful-work timing, with no polling worker.
Quiet-window busy >25%, CPU PSI waiting >5%, steal >1%, timed-arm steal >1%,
or a same-scenario raw-WRITE max/min spread >10% across repeats marks the result
`NOISY`. Missing/reset counters mark it `UNKNOWN` unless noise is already proved.
Both set `performance_validity.performance_usable=false`; consumers must exclude
them from performance decisions while preserving byte-exact correctness results
and all measurements in `build/tests/fast-test/latest.json`. The table prints
one compact quality status and exclusion reasons; no automatic retry occurs.

Before a source-performance comparison, declare primary endpoints, a practical
effect threshold, matched inputs, counterbalanced source order and a fixed run
count. Preserve exact source hashes for dirty development variants. Use paired
intervals and an appropriate direction test; adjust for the declared comparison
family when claiming significance across devices/content. Report excluded pairs
and assumptions. Do not promote a marginal gain/loss from a mean alone, interpret
an interval crossing zero as equivalence, or keep sampling until significance
appears. Historical cross-report changes remain descriptive evidence.

For passive cross-CPU tracing, globally sort per-CPU records by timestamp before
correlating events. Validate the timed population and complete event pairs
against independent operation/request counts; no reported ring-buffer loss is
not proof of completeness. Reject incomplete correlations explicitly, even when
the byte oracle passes. Admission/completion CPU identity and instrumented
`bio_endio()` wall time establish an association only: placement, tracing,
interrupts and workload progress can confound it. Do not turn that association
into a causal speedup, exact CPU cost or a raw-device comparison.

These are conservative development screening thresholds, not statistical
qualification or proof of causality. `SCREENED` means the checks passed, not
that the host was idle throughout. Timed busy/PSI alone must never reject a run:
the workload and kernel workers contribute to those counters. Mid-pair noise,
affinity-local contention or virtualization pressure invisible in guest steal
can still escape detection. A single repeat cannot establish raw-control drift.
This screen does not apply to the deliberately contended ID36 gate and does not
change `make test`, its exit codes, publication or qualification criteria.

### Published completion ownership gate

The lower-WRITE notification test executes the actual callback body under both
dm-io ABIs. On completion publication, a controlled waiter immediately attempts
the final queue-lock drain gate. Notification must be queued before that gate
can pass; cover success, ordinary error and the separate unsupported bitmap.
Reject target/slot dereferences after final unlock. This models an adversarial
interleaving, not a reproduced kernel crash. Loaded suspend, retained faults
and resource-pressure qualification remain necessary for the kernel path.

The owned serial smoke RAM device uses timer completion (irqmode 2, 14,000 ns),
with its existing one-queue/depth-one geometry, so detached lower completion can
exercise ACK ownership. This correctness-only model does not change the mixed
performance envelopes. A dedicated no-verify/retain-ms-2 mapping runs 32 private
persistent WRITE lanes on disjoint pages. The gate must observe a positive
handoff while writes are ongoing, suspend/resume without force removal, verify
all 128 final pages, account exactly 16,512 successful upper WRITEs, and finish
with completion_active=0 and failed=0. It does not claim to freeze a particular
helper instruction at the moment suspend starts.

A fresh mapping injects lower WRITE fault 256 after actual successful handoffs.
Parallel writes must fail, the target must become terminal with one injection,
and completion ownership must drain. A fresh aligned direct WRITE must then
return exactly -1/EIO and increment the error counter without a new success.
The mandatory loaded marker binds these checks; missing, zero-activity,
wrong-volume, still-active or missing-failure evidence blocks qualification.
Actual target-body native tests cover busy-slot fallback, 4..64 bounds, close
between eligibility and lock acquisition, reuse while an old work call returns,
and failure before/during BIO delivery. Kernel queue scheduling and reclamation
still require the loaded gate and ID36 resource-pressure qualification.

## Scope discipline

This file specifies tests that current source must pass. It is not the archive
for retired optimization protocols. Once an experiment is settled and its
runtime/test control is removed, keep only any still-required regression or
safety assertion here; record the anti-retest decision in the ROADMAP evidence
table and leave detailed trial history in Git/report commits.

For the post-ID97 retention-idle repair, native tests must distinguish
block-saving deferred pack geometry from planner-only geometry. Two compressed
records may arm `single_pack_deferred` only when the complete SWZ extent fits
4KiB; three may arm it when the complete extent fits 8KiB. A two-record prefix
that needs 8KiB remains valid planner geometry but must not become an early-close
latch, including across RAW interleaving after the protected count-four boundary.
Source contracts must prove that the pressure hand never steals an unprepared
descriptor, retained READ-bypass credit requires an already-open staged WRITE
window, sampled two/three-record tails require a current bounded queue boundary or
queued WRITE followers plus a successful independent READ in the same continuing
PACK chain (or the dedicated post-pack READ boundary). Failed/finite closes
and zero-tail samples revoke the mark; cached READs are upper-wave evidence,
never lower-device service accounting. Worker-empty burst-target shrink remains unblocked
merely because an earlier chain completed. Existing ID63 cache-coherence
contracts retain the same open-window-only bypass rule. This supports
correctness review but cannot prove loaded I/O service. Owner `make test` must
compare matched raw/sync/async mixed and sustained QD1/4/8/32, SD/SSD/NVMe
profiles, lower WRITE bytes/requests, read p99, deadline/undersized-idle
attribution, full GC, retained faults and suspend/drain. SIMD compile/runtime
coverage must include SSE2, AVX2, AVX-512 and ARM64/NEON where hardware is
available.

## Required stages

A complete run includes:

1. Product/module/userspace/helper build.
2. Direct production-C native tests plus source, build-interface, report and packaging contracts. Harness scripts `tests/tools/deploy-nullblk.sh`, `packaging/package-dkms.sh`, and `tests/runtime/native/package-dkms-test.py` must retain executable mode (`0755`) so bounded runner contracts and direct invocation invariants hold.
3. Kernel W=1 build.
4. Kernel W=2 build.
5. Owned RAM-backed `null_blk` correctness, lifecycle/fault checks, matched mixed benchmark evidence and bounded write-only QD evidence.

The compile matrix must cover both Device Mapper `dm_io` ABIs currently
encountered by supported builders: the legacy error-only callback/signature and
the newer separate unsupported-bitmap callback/signature. Distribution
backports make kernel-version inference insufficient; Kbuild must feature-probe
the installed `dm-io.h`. Both synchronous and asynchronous unsupported
completions fail closed.

Stages are ordered and fail fast. Privileged device sessions must never overlap. If noninteractive privilege or safe owned-device provisioning is unavailable, the complete run reports BLOCKED rather than silently skipping loaded work.

On Secure Boot-enabled hosts, stage 1 uses the same root-build signing hook as
`make` and must leave the experimental `dm-swapz.ko` signed before any
loaded work can begin. Qualification never prompts for signing privilege:
the runner marks signing noninteractive and the helper may use only cached
`sudo -n` authorization to read a protected private key. Missing
authorization, signing tools/key material, or an indeterminate EFI Secure Boot
state makes the build stage BLOCKED. Repeated qualification must recognize an
existing signature from the configured certificate and must not append another
signature to an unchanged module.

## Direct production-C tests

Native tests compile the real `src/kernel/{codec,authority,engine}.c` where applicable. They cover codec integrity, authority publication, torn/short failure, overwrite generations, discard, zero-write representation, online packing, randomized authority, lower-run aggregation, flush/FUA accounting, retention/window policy and GC rotation/cost invariants.

Source contracts validate behavior that requires the Linux Device Mapper target itself, including BIO ownership, queue/drain ordering, null_blk-only admission, lower-I/O accounting and current report/build contracts. Source-string assertions are secondary to executable production-C coverage.

Execute the worker's actual batch-selection C block with rejected-probe
outputs of zero and a nonzero poison value: either fallback must charge one
ordinary BIO. Accepted coalescing/fan-out batches retain their actual counts,
the final one-BIO budget skips batch probes, and 64 ordinary completions must
exhaust the quantum exactly. The regression must fail on the old zero-charge
path; merely finding a decrement in source is insufficient.

## Retained-window scheduler qualification

Native tests must keep authoritative sampled tails ahead of dry four-record
closure, and must cover the device-relative idle bound (half service EWMA,
20us floor, retain_ms cap, deadline only ever earlier), the pure-WRITE
half-burst rule and the measured RAW-hand cost gate. Source contracts must
require the effective deadline to apply the idle bound only with no lower
WRITE in flight, a queued timer to move only earlier, and the RAW hand to
consult the measured LZ4 and per-block service EWMAs; they must cover
dependency-safe independent READ scanning,
one-quantum scan bounds and four-record no-overlap synchronous dispatch.
Only an exact-source owner `make test` with the loaded RAM-backed null_blk phase
can qualify useful READ/WRITE, p99, lower bytes/requests, SD/SSD/NVMe, GC and
fault/lifecycle behavior. Rootless checks alone are supporting evidence.

Native window tests must distinguish a successful READ serviced after a staged
two/three-record post-PACK tail from successful READ continuity in the same
accepted PACK chain; source contracts must enforce the queued follower gate. The bounded
candidate must reject singleton, pure-WRITE, sampled-target, K=1-busy and
pending-sample service-dry cases and reset the evidence on a nonempty flush.
Observe successful READ service from the single-BIO, independent read-slot and
parallel read-batch paths even when an earlier K=1 sample is still pending.
Native tests must prove pending sampling blocks dispatch without erasing a
completed READ observation. Source contracts must verify a later staged WRITE
revokes that observation and failed batched READs cannot create it.
Owner loaded qualification must compare the same useful mixed/QD trace and
lower-device bytes/requests; no improvement is asserted from native tests.

## Loaded correctness

Loaded tests use only newly created, positively owned, RAM-backed `null_blk`. Before and after use, verify device identity, size, major/minor, DM UUID, holders, mounts and active-swap aliases. Never substitute a physical or existing block device.

The deterministic lifecycle oracle must preserve exact readback, RAW fallback, zero elision and explicit flush behavior. The loaded qualification must also recreate a fresh target on the same positively identified RAM lower and force repeated live-GC evacuation under bounded capacity pressure. Passing GC evidence requires at least two nonzero victims/role rotations, nonzero GC lower READ and WRITE traffic, distinct victim/destination identities, and byte-exact verification of all 4096 logical pages after pressure. This proves loaded GC correctness/cost only on synthetic RAM; it is not physical-wear evidence.

The loaded correctness report must recognize only the exact retained WRITE-fault
pass marker produced by the aligned syscall probe:
`PASS_RETAINED_SYNTHETIC_WRITE_FAULT=retain_ms:2 injected:1 syscall_errno:EIO lower_write_delta:0`.
A missing `syscall_errno:EIO`, a different errno, a reordered marker
field, a nonzero lower-WRITE delta, or an unarmed fault must remain INCOMPLETE,
even when the loaded shell phase prints a PASS prefix. Keep all three
evidence producers in lockstep: the privileged script, the native parser
fixture, and the fake loaded `make test` fixture. Assert their exact marker
agreement in rootless tests; the official acceptance command is still
`make test` on an authorized owner host.

Retained-window suspend/resume must drain accepted ownership and verify all pages. Synthetic pre-submission WRITE and FLUSH injection must fail closed. Upper WRITE errors must be verified at both the target's BIO completion call and Device Mapper's clone end_io boundary, and by a dedicated aligned O_DIRECT pwrite(2) syscall oracle that requires -1/EIO for the injected first WRITE. The end_io hook must preserve prior error statuses and reject new successes after terminal target failure; its counts cannot substitute for the userspace failure gate. These synthetic failures are not evidence for torn/device-originated errors. Recreated owned DM mappings must validate the opened /dev/mapper block node's actual major:minor against the current phase's sysfs DM name and UUID after udev settles, not just dmsetup's name-based UUID. If the deliberately injected WRITE syscall does not return -1/EIO, report the probe return/errno plus write-fault call, injection, failed-state, upper-BIO completion and zero-elision counters before blocking; do not turn this into a pass.

Before any new owned RAM device is provisioned, loaded qualification may
ordinarily unload a pre-existing `dm_swapz` module when its readable numeric
reference count is zero. A positive count is recoverable only for exactly one
mapper with the private `swapz-demo-<token>` name, matching
`SWAPZ-TEST-<same-token>[phase]` UUID, no mount/swap alias, and exactly one
proven memory-backed `null_blk` dependency created under the
`nullb-swapz-*` configfs namespace. The complete lower-device ownership proof,
including mount/swap exclusion, must finish before preflight sends any signal to
a mapper holder. When a stale mapper has transient opens, preflight boundedly
settles `udevadm` and may terminate lingering userspace test processes only via
the canonical block node of that already-proven private mapper. The canonical
node must resolve to the same block-device identity as the private mapper before
any holder signal is sent. After zero opens are established, that stale harness
mapper then receives one bounded non-force
`dmsetup remove --retry`; the lower itself is preserved. If TERM/KILL cannot
drop a positive open count, treat the holder as potentially uninterruptible,
report that a host reboot is required before the next `make test`, and leave
the mapping untouched. Multiple mappings, foreign identities, active opens that
cannot be closed, mounts, swap aliases, non-null_blk lowers, ambiguous configfs
identity, or any removal race remain BLOCKED. Forced mapper/module removal is
never permitted. After cleanup the reference count must be zero and ordinary
`rmmod` remains authoritative against races.

Cleanup never force-removes uncertain resources. If identity or teardown is ambiguous, quarantine and fail.

The private loaded preflight is an executable repository helper and rootless
qualification must fail if its executable bit is lost. Privileged orchestration
still invokes shell helpers through `bash` inside the watchdog, but repository
mode is part of the harness contract and must not silently drift. Preflight's
required-command audit must include every unconditional utility it executes.
Mapper enumeration and lower-dependency parsing are explicit fail-closed
operations; they must not rely on an unguarded pipeline/assignment under
`set -e`. Stale-mapper identity, UUID, open-count and lower-device validation
must avoid runtime-dependent Bash extended-regex capture state; exact shell
patterns and guarded parsers are preferred so malformed input reaches an
explicit `BLOCKED:` path rather than shell status 2. Canonical mapper identity
checks must separately guard both `stat` calls before comparing device IDs. All native interface/source-contract tests that describe this ownership proof must assert the same exact shell-pattern/token contract and must not retain obsolete `BASH_REMATCH`/extended-regex expectations. The privileged preflight safety path must avoid runtime `=~` expressions and C-style arithmetic commands entirely; numeric sysfs/dmsetup fields are accepted only as canonical unsigned decimal text (`0` or a nonzero value without a leading zero), and bounded retry loops use fixed shell iteration lists. This keeps malformed host state on explicit fail-closed `BLOCKED:` paths instead of Bash runtime-status paths. Native source/interface contracts and rootless literal checks must track those exact non-arithmetic preflight forms (`[[ $refcount == 0 ]]` and `[[ ${#swapz_maps[@]} == 1 ]]`); obsolete arithmetic spellings are not valid compatibility requirements. Because ordinary preflight safety rejections emit `BLOCKED:` and exit one, a
status-two preflight return is classified as a shell/runtime harness failure and
must emit a concise `FAIL:` marker rather than disappearing behind filtered
stage-5 output. Rootless verification must run `bash -n` across every harness shell script individually to ensure syntax regressions fail rootless Stage 2 rather than reaching loaded execution. The rootless harness must also prove that
`source-contract-test.py` contains exactly one terminal test runner; duplicated
tails or duplicate `__main__` blocks are harness corruption and fail before
loaded qualification. Unexpected preflight command failures must be trapped
before any ownership mutation and reported only as numeric status and source
line. The diagnostic must not include `BASH_COMMAND`, paths, UUIDs, mapper
names, or other host-specific values; normal ownership/safety rejections still
use the explicit `BLOCKED:` paths.

Transient target teardown between benchmark or lifecycle phases (such as tearing down the target prior to live-GC evacuation and recreation in `deploy-nullblk.sh`) must similarly settle `udevadm` and use bounded non-force `timeout --signal=TERM --kill-after=2s 10s dmsetup remove --retry` to safely absorb transient `systemd-udevd` probe activity without failing or hanging.

Owned benchmark-pair final teardown must also settle after a successful mapper
removal before judging lower-device holders. During that bounded post-remove
settle, only the exact former owned `dm-X` holder is permitted to disappear;
any different holder is foreign/new ownership and quarantines immediately.
A failed mapper removal records numeric open counts before/after when available.
After a lower passes the full identity/holder/mount/swap audit, power-off may
boundedly wait for that exact null_blk sysfs device to disappear before configfs
removal. No wait authorizes force removal or weakens identity checks. Sanitized
reports must preserve the specific `QUARANTINED:` reason instead of collapsing
all teardown failures into one generic diagnostic.

Benchmark telemetry and storage-envelope parsers must safely handle directional workloads where specific operation latencies are omitted (for example, read p99 latency during write-only saturation or delta64 rescue sweeps), converting missing numeric fields safely without type errors.

### Direct-I/O and memory input qualification boundary (ID43)

Direct-I/O tests covering segmented and offset user buffers (via `transfer_segmented()` and `series_segmented()` with `pwritev`/`preadv`) qualify user buffer alignment, non-zero `bv_offset` translation, and multi-segment BIO boundary handling through the Linux block layer. In addition, explicit Transparent Huge Page (THP / `MADV_HUGEPAGE`) compound folio backing (via `series_thp()` with `--thp-write-series` and `--thp-verify-series`) exercises incoming direct I/O from 2MiB compound memory regions. Kernel-level passive inspection counters in `dm-target.c` observe:
- `bio_segments_gt1`: admitted BIOs spanning multiple bvec segments.
- `bio_segments_max`: maximum segment count observed on an admitted BIO.
- `bio_nonzero_offset`: admitted BIOs with non-zero within-page `bv_offset`.
- `bio_compound_folio_pages`: admitted BIOs whose backing memory is a compound folio (`PageCompound()` or `folio_test_large(page_folio())`).
- `bio_copy_fallback_pages`: write pages where direct LZ4 mapping was safely bypassed in favor of accounted copy fallback. This status field aggregates the ordered owner, background preparation producer, and ID150 submitter-preparation owners exactly once; changing execution placement must not hide fallback coverage.

Loaded qualification on owned RAM asserts `segs_gt1 > 0`, `segs_max >= 2`, `nonzero_off > 0`, `compound_pages >= 128`, and `copy_fallbacks > 0`, while preserving byte-exact verification across all segmented, THP, and cross-mode reads and writes with zero DM target failures.

The completion-handoff loaded fault gate must not rely on an early fixed lower-WRITE ordinal that can move ahead of the first handoff when preparation placement changes. The fixed 128-page × 129-round parallel series supplies 16,512 logical WRITEs; with the 64-record window bound and the eight known zero-elisions it guarantees at least 258 physical WRITE attempts per series. Fixed ordinals 32 and 256 each blocked once when preparation timing moved, and a slow four-CPU host qualified with only one handoff before attempt 256. The handoff/fault gate therefore injects on attempt 4096 and repeats the same fixed series on the same mapping, at most 16 times (at least 4,128 guaranteed attempts), stopping at the first non-success writer exit, which must be the injected failure. The preceding live suspend/drain probe likewise repeats the same series at most 16 times, polling each writer until it exits (no fixed poll budget), and suspends only after a handoff newer than that pass's baseline is seen while the writer is alive; completed WRITEs are counted for that pass only. The fault gate still requires at least one real offloaded completion batch before terminal failure (handoffs are refused once the target has failed) and reports every predicate (handoff count, active state, target failure, fault calls/injection, upper error completions, passes) on failure. This changes only qualification timing; the production fail-closed path and write-fault mechanism remain unchanged. BIO shape and compound folio inspection in `swapz_map()` strictly gates `bio_for_each_segment()` iteration to data-carrying operations (`REQ_OP_READ` and `REQ_OP_WRITE`) with positive sector counts, preventing invalid bvec traversal on non-data requests (e.g., `REQ_OP_DISCARD` or empty flushes). Failure context extraction in the test harness explicitly distinguishes each loaded subphase (`START_LOADED_COMPOUND_BIO`, `START_LOADED_LIVE_GC`, `START_LOADED_DISCARD_TRIM`, `START_LOADED_PACKED_PLACEMENT`).
Privileged qualification shell entrypoints under `tests/tools/` are executable repository artifacts; content-only Git-tree updates must preserve their existing executable mode so CI and the public Make contract exercise the same entrypoint the owner runs.

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

The default operator output must place the qualification decision ahead of
native-only screening. On BLOCKED, FAIL or missing matched loaded sessions, it
prints the gate and why no new raw-relative performance claim is possible,
without dumping diagnostic/native tables. On qualified runs it keeps the
synthetic serial-depth and fast QD32 mixed raw/sync/async comparison, accepted-
work lower-idle (including undersized and preparing-head attribution), K=1
ready-run wait, sustained QD1/4/8/32 raw-versus-async service, and separately
labeled async-versus-sync paired confidence intervals. Missing telemetry is
unavailable, never zero. Internal rootless fixtures may still exercise the
legacy detailed Markdown renderer, but it is not the default terminal report.
The saved JSON, qualification gates, stage progress, safety checks and exit
codes are unchanged.

### Evidence-monotonic report publication

Report publication must be strictly evidence-monotonic. When publishing `test_results.json` to `origin/main`, if `origin/main` has advanced while the test suite was running, the publisher fetches `origin/main` and inspects the remote `test_results.json`. If `origin/main` already carries qualification evidence from a tested commit that is an ancestor or newer descendant of the local tested source (`git merge-base --is-ancestor local_tested remote_tested`), publication is declined with `SKIPPED_GIT_SYNC` so that delayed or concurrent runs cannot overwrite newer qualification evidence with older results. Furthermore, the ancestor evaluation must fail closed: if `git merge-base` returns an error status (exit code > 1), publication halts with `GIT_SYNC_FAILED` rather than proceeding under uncertain ancestry.

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
under 96 columns so captured stdout stays copy/pasteable and readable. When a
paired confidence summary would exceed that bound, wrap at a metric boundary
rather than dropping a metric or weakening the width limit.
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

The human-readable console report must interpret loaded product tables against
the raw/off control, not merely against another swapz setting. It must state the
direction of useful throughput, latency and lower-device work, and distinguish
a project-aligned direction from a trade-off or regression. Internal A/B
controls remain useful for attribution, but beating sync or feature-off alone
is not a product win when swapz still trails raw. Mean-value interpretations
must identify themselves as directional; paired confidence intervals remain
the statistical qualification.

Timing labels must describe the measured scope rather than call order. When
delta64 transform time and LZ4 compression time are separate columns, the
compression column is `LZ4 ns`. A combined label may mention delta64+LZ4 only
when one measurement includes both operations. The console must not use
`LZ4-2` as a user-facing timing name.

## Evidence levels

Source contracts show structure, not loaded semantics. Native C shows portable product logic, not Device Mapper runtime. W=1/W=2 shows compilation, not correctness. Owned RAM-backed loaded tests show real kernel BIO behavior on the test host, not physical-media benefit. Only separately authorized physical testing can establish behavior on a particular real device.

### Optimization-round history artifacts

After each optimization round, the private history plotting helper reads the
committed `test_results.json` revisions and emits a six-target default-LZ4 mixed
READ/WRITE chart, mixed p99 chart, lower-WRITE bytes/requests savings chart and
separate persistent-WRITE QD1/4/8/32 chart. Use standard plotting tools; rendering
dependencies stay outside production and ordinary qualification. Rootless tests
exercise the pure report selector/normalizer and line-break logic without a
plotting dependency.

ARM64/NEON plus the seven-online-CPU profile selects this VM's historical
cohort; old reports lack an immutable VM identifier, so record that limitation.
Require overall PASS, default async preparation and a recorded delta64 state
for mixed points, and matching source/fixture/trace between each pair. Delta64
off and on are separate series: the production default became rescue-on, so the
line breaks there instead of joining LZ4-only history. Exclude
failed/blocked reports and other or unproven hosts. Never pool optional delta64
positive write-only envelopes with ordinary mixed service, or historical wave
drivers with persistent WRITE. Missing targets/metrics are absent, never zero.
Kernel/model/content/replay discontinuities break lines.

Positive percentages mean useful throughput gain, p99 reduction or host-WRITE
savings versus that report's raw control. Mixed rates are ratios of matched-arm
arithmetic means, and may differ slightly from the reporter's differently pooled
raw column. CSV/JSON must retain report and tested-source SHAs, kernel, local
dates, compatibility identity, absolute rates and ratios. Historical host load
was not quiet-screened; cross-report changes are descriptive, not causal or
paired confidence estimates. Keep unqualified development trials separate and
state the last qualified source when a round creates no new owner report.

## Current qualified baseline

The latest successful ARM64/NEON VM owner matrix tested exact source
`3362fa020bf34379ac609840669bce79e479298b` and published report-only commit
`87180ee5b8a8` (same production C as `005592d`). That report says PASS
for all five stages: build, native/rootless, W=1, W=2 and owned-RAM loaded
qualification, including lifecycle/fault/GC and ID36 resource pressure.
Later source changes require their own complete owner `make test`.

That run reports fast mixed async useful WRITE +9.9% versus raw, SD mixed
+400%, and fast sustained QD1/QD4/QD8/QD32 -3.7/-11.7/+21.7/+52.2%.
SATA/NVMe envelopes and fast QD4 remain below raw.
These are host-specific synthetic results, not universal raw parity or physical
endurance evidence. Preserve independent lower WRITE bytes/requests as the
host-I/O endurance proxy and circular segment allocation as logical fairness.

Production keeps ordinary LZ4 acceleration one, one unbound preparation
producer, the bounded 64-slot RAW+compressed reservoir, lower-WRITE depth one,
independent READ fan-out, the eight-block ID63 cap, packed placement and SWZ
1/2/4-block extents. ID107–ID108 independent dispatched-run READ service and
deferred acknowledgements are now owner-qualified; the fresh K=2 development
experiment in ROADMAP ID110 is rejected rather than promoted. Delta64 is now
default-on with second-pass LZ4 acceleration four (ID115), qualified in that
owner run. The later `005592d` adds DELTA64_SHUF8 and the faster NEON inverse;
the complete ARM64 matrix above now qualifies it. The owner x86 matrix on exact source `005592d` passed
all five stages (report `4886c4d79a362b546b69bc5f9356be05ec2f536f`), including
scalar/SSE2/AVX2/AVX-512 runtime qualification and loaded resource pressure.
Keep the x86 eight-CPU result out of
the seven-CPU ARM64 history.
Representative-content prevalence, long-run churn, actual
kernel swap and physical media remain separate qualification gates.

## Immediate K=1 critical-path profiling gate (ID114)

The profiling-only source keeps K=1, the existing four-record service rule, one
unbound preparation producer, the 64-slot reservoir, ordinary LZ4 acceleration
one and current SWZ geometry. `make fast_test` defaults to three repeats each
of SATA mixed, NVMe4 mixed, fast mixed, fast QD4 and fast QD8. The existing
pre/post host-noise and raw-repeat-spread screens remain exclusion gates:
NOISY/UNKNOWN runs may verify correctness and telemetry plumbing but cannot
support a performance keep/remove decision.

The timed kernel interval must expose nonnegative
`write_admit_worker_samples/write_admit_worker_wall_ns` and synchronous
four-record `sync4_*` counters. For every interval,
`sync4_lower_write_ns + sync4_nonio_ns == sync4_wall_ns` and
`sync4_reissue_samples <= sync4_windows`. Admission timing is accepted WRITE
to first ordered-worker ownership; accepted-idle
`accepted_work_lower_idle_worker_unscheduled_ns` remains the narrower
wake-to-worker scheduling attribution. Ordered-worker scheduler-update runtime samples are separate diagnostics;
they do not establish an exact split among CPU, lower-I/O sleep and off-CPU wall
time. After warmup and before the timed status snapshot, the replay harness sends
the internal `profile_epoch` DM message. That message clears only the passive
previous-sync4 timestamp, so the first timed reissue sample cannot bridge the
warmup/status-snapshot boundary; it must not reset cumulative counters or any
correctness/scheduling state.

The production message callback must return 1 with `profile_epoch=1`, so DM
core exports the reply to `dmsetup`; returning 0 suppresses that output even
when the command succeeded. Rootless coverage executes the actual callback
with minimal DM stubs, checking the return value, exact reply, timestamp reset,
unchanged cumulative counters and rejection of unknown commands/wrong argument
counts. The replay harness must continue rejecting a missing acknowledgement.
Owner report `a4ff2205fa95` on `de79f2ec832d` passed stages 1–4 and loaded smoke
but failed this acknowledgement at the first mixed swapz session. The later
owner run on `b86fefd` (report `0d97e99`) passed the repaired handshake and all
five qualification stages, including the new defaults.

Development decisions retain absolute raw/swapz useful throughput, READ/WRITE
p99 and independent lower WRITE bytes/requests alongside the compact phase
breakdown. Detailed per-run telemetry remains under
`build/tests/fast-test/latest.json`; it is development evidence only and never
updates `test_results.json`. After profiling, test at most one narrow
production-C candidate at a time with matched screened `make fast_test`
comparisons. A kept candidate requires the ordinary correctness stages, ARM64
history refresh, and exact-source owner `make test` qualification. Profiling
counters themselves do not establish a performance gain.

## Deferred optimization evidence gates

- **ID113 folio locality:** currently a source audit and bounded measurement
  proposal, not an active layout policy. Existing THP/compound direct-I/O tests
  establish buffer shape and byte correctness only. A future sampler must
  distinguish upper WRITE provenance, recover later READ cohorts through current
  logical-page/generation tags rather than READ buffer pointers, and account for
  window censoring, pointer reuse, eviction, overwrite/DISCARD/zero/GC invalidation
  and failed publication. Controls must separate folio hints from logical
  adjacency, reused transfer buffers and readahead. Representative actual-swap
  collection is outside the current owned-null_blk gate. A later policy needs
  full-window geometry/run equivalence and measured CPU, useful READ/WRITE,
  p99 and lower-I/O evidence; no larger upper BIO or active-swap test is implied.
- **ID38 lower-WRITE depth:** closed for the current product. Repeated paired
  depth-1/depth-2 evidence did not establish a useful service benefit.
  Production is fixed at depth one; the runtime selector, second-slot allocation
  and append path are removed. Any future K>1 study is a new architecture
  experiment with immutable per-run ownership and FIFO publication gates.
- **ID39 helper concurrency:** refuted and removed from current source. Do not
  restore a helper workqueue merely to satisfy historical telemetry.
- **ID60 same-extent grouping:** refuted and retired. Do not keep a dedicated
  loaded A/B after the code path is removed; ordinary reads already use the
  shared extent/metadata caches.
- **ID63 adjacent READ coalescing:** production keeps `read_coalesce=1` by
  default. Retain five matched fast rounds and five matched serial-depth rounds.
  The idle SSE2 matrix showed a fast sequential throughput loss despite request
  reduction, while serial-depth service remained strongly positive. The next
  exact-source run therefore qualifies the cached-head fast reject before any
  policy change: a FIFO head already satisfied by shared cache residency must
  return before the bounded 64-BIO candidate scan and private-slot preparation.
  After one successful combined lower READ, each constituent may complete only
  after its own authority/generation checks, metadata and payload CRC validation,
  decode, and upper copy have succeeded. A later constituent failure fails the
  target and every BIO still owned by the worker; it does not retroactively
  invalidate an already fully verified constituent. A combined lower-I/O
  failure publishes no constituent success. Every merge remains exact, same-segment,
  <=8 blocks total and zero-padding; `parallel_read_coalesce_extra_blocks`
  stays zero and defensive skip-other stays zero. Eligibility must use shared
  cache metadata without private-slot memcpy, and source contracts must prove
  successful upper BIO completion precedes shared LRU absorption.
- **ID64 one-shot in-flight-zero shrink guard:** retired. Do not restore the module parameter, shrink helper or loaded A/B. Compatibility status fields stay zero so existing report parsers remain stable.
- **K=1 shallow detach gate:** fast QD4/QD8/QD32 require five matched sync/async pairs. Acceptance requires the prior QD4 regression to disappear, QD8/QD32 to keep statistically positive async gains, and fast mixed lower request inflation to improve without useful-throughput or read-tail loss.
- **K=1 read-bypass detach guard:** the guard is fixed on. Two-host paired evidence showed that relaxing it activates substantially more detach work without improving useful throughput or read tail latency, so the module override and routine A/B are retired. `pipeline_read_bypass_skips` remains passive pressure attribution for the active guard only; it must not alter scheduling or justify reopening the policy without a new workload.
- **Device-model limits:** every report must distinguish the configured null_blk MiB/s cap from the analytical unmerged-4KiB latency ceiling (4096 * hw_queue_depth / completion_nsec). The console must show both in decimal MB/s and must not call the calculation a measured bulk calibration.
- **ID65 synchronous read cleanup:** owner-qualified. Any non-ID63 candidate
  must now return before slot preparation/priming; no standalone same-extent
  slot execution remains. Fast/serial ID63 retain five-pair confirmation.
- **ID66 discard scratch cleanup:** owner-qualified. Source/native contracts
  continue proving the temporary live-reference decrement is exactly restored
  before return/commit, including an error after a validated shared-extent page.
- **ID67 predictive rescue:** rescue is default-on by owner decision; the
  paired A/B off arm pins `--no-delta64-rescue`. The second LZ4 pass
  has a separate read-only `delta64_lz4_acceleration` control, default 4 (the
  value the A/B qualified; `PRODUCTION_DELTA64_LZ4_ACCELERATION` in the
  reporter). Standard sessions run that default. The standard rescue A/B fixes
  that control at 4 in both arms so rescue remains the
  only changed policy while testing whether lower second-pass CPU cost closes
  the idle-SSE2 service regression. RAW or >2024-byte LZ4 baselines use
  threshold 24 and require a strictly smaller candidate. A
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

The immutable lower-WRITE production policy is fixed at depth one. Repeated
paired evidence did not establish a useful depth-two service benefit, so the
runtime depth selector and routine depth A/B are retired. Authority publication
and upper-BIO completion remain serialized after the sole immutable lower run
completes. Historical depth-two code may be removed mechanically only while
preserving the byte-exact, barrier, suspend, teardown and failure contracts.

Generic **background-worker** ordinary-LZ4 preparation concurrency remains
blocked by the prior shallow-backlog evidence. Delta64 background preparation
is likewise fixed at K=1: two-host paired evidence found no service gain from
K=2 and materially worse p99/preparation cost on the newer host, with earlier
K=4 regressions. The runtime preparation-width selector and routine K=2/K=4
qualification are retired; Git history is the archive. Async background
preparation therefore owns one producer lane regardless of delta64 policy.

ID150 is a distinct submitter-context placement experiment, not permission to
raise that background width. Qualification must prove byte-exact ordinary,
RAW, zero, delta64, fault, suspend/drain and GC behavior with the candidate
default enabled. Drained status must show `submitter_prepare_active=0` and
source contracts must prove the scratch pool is preallocated/bounded, claim
failure falls back without waiting, and release/acquire ownership prevents the
ordered worker from touching a submitter-owned FIFO head. Performance evidence
must retain submitter claims, lane/page misses, active peak, owner deferrals and
submitter wall/CPU/LZ4/copy/CRC counters. Claims/pages/timing are measurement
deltas; `submitter_prepare_active_max` is deliberately the loaded-target
high-water mark and is not reset by `profile_epoch`. Global WRITE-copy bytes
and LZ4/copy wall totals include submitter work exactly once. Treat those clocks as
attribution, not additive CPU totals. ID36 must remain within its resource-pressure gate;
the extra scratch allocation is part of the candidate cost. The source contract
also permits the submitter helper between the final admission-lock release and
`DM_MAPIO_SUBMITTED`: preparation must finish before `swapz_map()` returns,
and the helper must not dereference per-BIO/prepared ownership after releasing
the submitter-active gate.

For mixed loaded pairs with asynchronous preparation enabled, positive
`prep_lower_write_overlap_starts` still proves background-producer preparation
began during a lower WRITE. ID150's submitter preparation is a different owner
and is not counted by that producer-only metric. The activity gate may instead
accept positive `submitter_prepare_pages` with `submitter_prepare=1`, claims
at least as large as completed pages, and `submitter_prepare_active=0` at
the drained status boundary. It must reject both paths idle, missing counters,
or outstanding submitter ownership. Submitter pages alone do not prove
temporal overlap with lower I/O; the observed producer overlap remains reported
unaltered and performance inference remains dependent on the actual paired
service, lower-traffic and latency data.

The rootless Make-interface contract must execute the loaded pair's full
asynchronous-preparation shell gate, not a truncated nested branch, with
synthetic drained statuses for producer-only work, submitter-only work,
no work, disabled submitter policy, claim-count mismatch, and active ownership.
This preserves test coverage of both valid placement paths without replacing
the required owner-loaded byte-exact and lower-I/O checks.

The positive delta64 rescue off/on A/B must likewise accept genuinely
prepared pages from either the background producer
(`delta64_prepare_pages`) or ID150 submitter context
(`submitter_prepare_pages`), because the former field intentionally counts
only the background producer. This is not an excuse to disable the positive
control: every enabled rescue arm still requires nonzero classifier passes,
attempts, adoptions, transform time and total rescue time; the normal timed
telemetry contract checks submitter policy, ownership quiescence, claim/page
conservation and complete WRITE-copy attribution. Disabled rescue arms must
still have zero delta64 activity. Rootless reporter tests must prove the
producer-only and submitter-only positive cases, zero-activity rejection,
missing delta64-adoption rejection and invalid ownership accounting rejection.
Do not claim this placement change itself improves service or endurance: the
five-pair timed outcome remains the performance decision.

Parallel READ service is separate: it requires private read scratch and must
dispatch immediately when lower I/O is idle. Reordering/coalescing is permitted
only for reads already waiting behind active lower work.

Genuine device-originated/partial lower errors, representative long-run
resource/churn pressure, larger controlled cold-read working sets, automatic
device-queue-depth policy, actual kernel swap, physical-device behavior and
physical endurance remain open. The current owner matrix already satisfies the
bounded ID36 deliberate CPU-oversubscription/low-RAM gate and the promoted
five-pair statistical protocols. Physical-device admission remains separately
blocked.


### zswap collaboration qualification

See [context.md](context.md) for Linux swap and zswap code paths and the staged
[ROADMAP.md](ROADMAP.md) for planned origin and RAW-bypass experiments.
This is a **future actual-swap gate**, not authorization for `swapon` or
`swapoff` in today's owned-RAM `null_blk` qualification scope.

Before origin-aware code can promote, source/native fixtures must prove
explicit origin propagation across simulated BIO split/clone, correct
unknown-origin fallback, producer-claim/snapshot/RAW atomicity, exact
one-owner completion, and no compressed result republished after RAW selection.
Tagged bypass must perform zero ordinary LZ4/delta64 attempts and produce
byte-exact readback through the existing CRC/generation and GC mapping rules.
Include duplicate-page ordering, overwrite, DISCARD, PREFLUSH/FUA,
suspend/drain, fault/uncertain lower completion, and preparation-slot cleanup.

After separate owner authorization for actual kernel swap, loaded tests must
force and distinguish: zswap accepted with no backing write, initial zswap
rejection with backing write, and later stored-then-evicted zswap writeback.
Record tagged-origin counts, attempts skipped, useful throughput/p95/p99,
CPU/RAM and independently measured lower READ/WRITE bytes/requests against
matched zswap-enabled control runs; include swap-in and GC effects.
A CPU/throughput win with materially greater lower-device traffic is a
tradeoff, not automatic qualification. Locality-aware layout remains
telemetry-only until measured swap-in correlation justifies the tie-break.

### Folio-locality observation and packing qualification (ID113)

The [context.md](context.md) WRITE-cohort identity and Linux-version caveats
are required background. This is **not** an existing performance claim.
Do not confuse the direct-I/O `series_thp()` compound-backing regression
with actual anonymous swap/folio locality.

Native/source and safe owned-RAM loaded fixtures must check bounded source
folio observations only during owned WRITE BIO lifetimes, no retained folio
pointers/references to swap-in, and cache association exclusively after
confirmed mapping publication. Exercise overwrite, DISCARD, generation/slot
reuse, failed/partial/uncertain lower I/O, GC relocation, suspend/drain
and bounded cache eviction; every stale or missing cohort lookup must be
unknown, never a correctness input. Prove one completion owner and no
change in authority, bytes, publication order or output without enabling
any locality policy.

Any subsequent actual-swap correlation claims require separately
authorized safe kernel-swap qualification, including a fixed kernel source,
observed backing READ timing, comparison with logical adjacency and
arrival order, cache coverage, and readahead / swap-cache / zswap effects.
Target-only READ observations measure backing co-access, not all user
faults. The current THP transfer-buffer tests cannot establish it.

If an equal-length permutation policy is proposed, direct production-C
planner/source tests must compare the **entire resulting physical run**:
same encoded-length sequence, lower bytes, cold-read cap, extent classes,
extent count, physical run count/splits and requests, alignment padding,
segment-tail waste, read CRC/generation correctness and CPU/dispatch cost.
Reject any candidate that delays an otherwise dispatchable WRITE, adds
extra blocks/requests or crosses a same-page/barrier dependency. No
alternative test entrypoint; `make test` remains the official qualification
command and `make fast_test` remains development-only.

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
They must also mirror every helper built transitively by the root Makefile, including private qualification helpers, so the fake-Kbuild incremental test exercises the real dependency graph without changing the public Make goal contract. The Make-interface contract must assert that transitive edge explicitly, not merely the helper target's presence.


Native shell regressions source shared helpers only from `tests/tools/`.
Current reports, test output and product-facing diagnostics use `swapz`;
implementation-generation labels are not permitted outside explicit disk-format
history.


Native engine tests call the same batched write entry point as the product.
Tests that omit bulk callbacks thereby exercise its production sequential
fallback; no test-only write wrapper is part of the engine API.


Post-oracle mapper teardown remains fail-closed but may use a bounded
non-force `dmsetup remove --retry` when the correctness marker has already
proved the phase. This exists only to tolerate a transient userspace/udev open;
persistent opens still fail with before/after open-count diagnostics. `--force`
remains forbidden.

The owned benchmark table validator must match the current Device Mapper
constructor exactly. Removed constructor fields are removed from replay parsing
in the same change; stale positional compatibility parsing is forbidden because
it can reinterpret ordinary options as fault injection and falsely BLOCK a
healthy product arm. Benchmark diagnostics and errors use the product name
`swapz`, never implementation-generation labels.


The retained suspend/resume oracle gates on observing an open retained window,
successful suspend/resume, a nonfailed target, and byte-exact verification of
all accepted pages. The bounded private writer must remain blocked on a private
start gate until the status sampler has completed one valid status read and
announced readiness. Only then may the writer be released. This sampler-first
handshake prevents a fast child from consuming the initial 4ms retention
opportunity before the separately scheduled observer runs. After release, the
sampler polls without an added sleep for exactly as long as that writer process
remains alive. A fixed poll-count loop is forbidden. The sampler must still
observe `retain_timer_arms > windows`; historical timer activity is not a
substitute for an actually open window. Synchronization waits are bounded and
must terminate both helper processes before reporting failure so teardown
cannot inherit a blocked FIFO reader. The concurrent lifecycle writer and subsequent
byte-exact verification processes run with a bounded 30s timeout headroom across
dmsetup suspend and resume operations, ensuring host scheduling load during post-compilation
drain does not prematurely terminate the writer, and dumping writer stderr on unexpected exit.
Suspend qualification must rely on Device Mapper's callback ordering, not a
time-based completion grace period. Production source must place the closed-
admission drain in `->postsuspend`, keep `->presuspend` free of that drain,
and contain no deferred drain-completion BIO list/work item or fixed
`usleep_range()` barrier guess. DM core blocks new I/O and waits for existing
target I/O before `->postsuspend`; `->resume` must reopen swapz admission
before the core releases deferred I/O. If the lifecycle writer fails, report
its exact exit status plus current target status on the fail-only path. The
owned loaded harness must remain executable in the Git tree; losing its execute
bit is a qualification failure, not an operator workaround.
The physical/production retention ceiling remains 4ms. The owned null_blk-only
lifecycle oracle may use an explicit 64ms retention interval solely to make the
open-window observation schedulable on very slow hosts where one separately
spawned `dmsetup status` round-trip can exceed 4ms. That longer interval does
not qualify or select a production retention policy; benchmark arms remain on
their separately qualified retention settings. The sampled lifecycle window
can still legitimately expire between observation and the separate suspend
request, so the oracle must not require a specific close-reason counter
afterwards. Source contracts must prove values above 4ms are rejected for
non-null_blk backing and that the extended bound is restricted to owned RAM
qualification.
Loaded failure reporting skips the generic cleanup epilogue so the preceding
specific sanitized failure remains visible.


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


Service-proven retained closure qualification has one PACK_READY owner: the
serialized worker. Source coverage requires `swapz_accept_write()` to record
pack geometry without emitting PACK_READY, while the worker may close only
after refreshed local/incoming queue state, pending post-PACK tail sampling,
and the existing burst/tail/service evidence. A successful independent read
while a retained write window is open must be boundedly attributed to that
window and cleared when the nonempty window commits.


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


Retained-target qualification requires source coverage for the single
worker-tail PACK_READY owner. Admission may update
`accepted_burst_pack_ready` and sampled-geometry state, but must not emit
PACK_READY. Source contracts must remove the retired admission-close helper
rather than preserve it as a compatibility alias. A detached PACK_READY sample
must remain pending while K=1 is in flight; quiescent-state reset is legal only
when both the retained batch and in-flight run are empty. After K=1 completion,
the worker must sample before consuming the next FIFO and distinguish the
already-staged `batch_count` prefix from queued `local + incoming` followers
within the remaining 64-record room.

The completed contribution to burst learning after a PACK_READY lower run is
the count from that one just-completed generation. It must not accumulate older
PACK_READY generations whose upper BIOs have already been completed and may
have re-entered the closed-loop workload. A non-PACK split piece may still add
to the current generation until a PACK_READY boundary. The post-completion
sample is then consumed exactly once: only the already-staged pre-completion
prefix may raise the learned target. Queued `local + incoming` followers still
make the finite sampled tail explicit, but must not be added to the completed
generation because they may contain immediate resubmissions from those same
writers. A staged-only tail installs no immediate `retained_tail_target`, even if
previously serviced READs marked the worker's mixed wave.
A staged-only sample must not remain pending merely to suppress PACK_READY, so a
valid service-dry or learned-target close can proceed without burning the
absolute deadline.

First-pack recognition remains selective two-compressed/one-block or
three-compressed/two-block geometry; four ordinary compressed records fitting
the 16KiB class must still not become a first-pack shortcut. Bulk RAW records
are excluded from compressed-pack membership rather than poisoning all later
compressed geometry. Native coverage must prove: one RAW plus two exact
compressed records can establish the 4KiB first pack; RAW-assisted geometry at
total count four still cannot establish a first pack; one RAW plus four
compressed records can establish the 8KiB second pack; one RAW plus six
compressed records can establish the 16KiB second pack; a newest RAW admission
does not manufacture a transition; invalid compressed lengths, disabled
retention and restricted read budgets still fail closed. Source coverage must
also require early compressed-count/extent-cap rejection and one direct
first-two-compressed prefix scan rather than an O(n^2) total-prefix loop. The
flush planner and on-disk extent classes remain unchanged. The worker then restores unfinished
local work to the accepted FIFO and re-evaluates PACK_READY before the retention
timer can be armed.

These scheduling rules are architecture-neutral. The public `make test`
matrix must continue to build and qualify the existing predictor backends:
SSE2/AVX2/AVX512 objects on x86_64 and NEON on arm64, with runtime execution
only on hosts advertising the required ISA. A scheduling change is not allowed
to weaken or bypass those existing backend checks.

Tail learning must be gated exclusively by
`pack_close_pending_tail_sample`; pre-PACK sampling from a deferred first
pack is forbidden. The sampler is completion-only: it returns directly while
K=1 exists, so the historical one/many-inflight sample buckets remain
compatibility telemetry and must not regain active increments. Source
contracts should require the direct `swapz_has_inflight(ctx)` guard rather
than preserving a dead local alias or unreachable branches. Source coverage
must also prove the zero-count flush return
precedes retained-state clearing, normal and independent retained READs refresh
accepted followers after synchronous service, and tiny dry-residue closure is
gated by read/fence evidence rather than a prior packed chain alone. After a
PACK_READY close with no already-accepted follower, that read/fence evidence
must be consumed so it cannot authorize another dry-tail singleton close.
Source coverage must preserve DUPLICATE continuation semantics because the
current WRITE continues after that older batch is flushed.

ID83's first exact small-tail attribution is settled by owner report
`685c52f5a272`; full-deadline suppression is refuted by `f0d2e04e50e7`,
and the later 500us/cache-hit-pivot candidate is refuted by report
`efb713c06daa` on exact source `829cdbe0d9eb`. Relative to the immediately
preceding `e17f05a1c256` result, fast mixed async useful WRITE fell
38.26 -> 32.21 MB/s while lower-WRITE requests rose 2255.0 -> 2572.6 and mixed
READ p99 rose 0.823 -> 1.208 ms. The candidate also accumulated 756.58 ms of
accepted-work lower-idle undersized-batch time. These are product-facing
regressions, so distribution evidence that originally motivated the 500us wake
does not justify retaining it.

The replacement contract is work-conserving and timer-free. Pure-WRITE
post-PACK tails of two/three remain below the qualified four-record floor. A
two/three-record tail may become an exact finite sampled target only when the
sampler's own bounded current queue snapshot encounters an independent READ or
other accepted non-WRITE boundary. Earlier wave-level READ evidence is not
sampling authority and must be cleared on every nonempty WRITE-window flush. A
successful independent READ serviced after a two/three-record tail was already
staged remains a separate, dedicated post-pack boundary path. Source contracts
must prove the sampler does not consume `retained_wave_read_seen`, the single-
BIO path sets that mark only after actual lower READ I/O, normal and bounded
parallel READ paths cannot turn a cache-only event into sampled-tail authority,
true worker-idle and hard ordering boundaries still clear retained evidence, and
the mapper never mutates worker-owned scheduling state.

Pack-readiness qualification must separately cover the RAW-interleaving state
repair. The total-count-four first-pack guard remains in force because its
removal previously split QD8 into synchronous 4+4 service. After total count is
greater than four, only an earlier block-saving two-compressed-record/4KiB or
three-compressed-record/8KiB prefix is persistent finite evidence and must
remain recognizable even when RAW records or later compressed records change
the current exact geometry. Two compressed records requiring 8KiB are
planner-only geometry and must fail both current and prior deferred-pack
readiness. Both RAW and compressed admission paths must re-evaluate the
block-saving proof. Native tests must cover count four remaining ineligible,
count five recovering a valid earlier block-saving pack, and an explicit
two-record/8KiB case that remains ineligible across RAW slots. Geometry fixtures
that temporarily mark a record RAW must restore both its RAW flag and compressed
length before reusing that array for later exact-pack assertions; otherwise the
fixture is testing stale mutation rather than policy.

The refuted suppressed-tail lifetime counters and their replay/reporter schema
are removed in the same change. Keep exact target-2/3/4 PACK_READY attribution
and accepted-work lower-idle partitioning so the new scheduling decision remains
measurable without retaining dead policy state. There is no microsecond wake,
timer rearm, second timer, mapper atomic or future-arrival grace period. Source
contracts must scope fail-closed READ ordering to the independent-READ service
block rather than an earlier deadline-flush block, and mixed-wave state may be
set only after the independent READ has actually completed successfully; a READ
that merely reaches the worker before an expired window flush is not evidence
for the preceding window. Geometry-latch counter assertions follow the helper
that owns the latch, not the admission caller, and generated telemetry-field
checks must interpolate the field name rather than compare placeholder text.

Loaded qualification must use the exact-source owner `make test` matrix and
judge product-facing service before internal attribution. The sustained
write-only matrix uses five counterbalanced async/sync pairs for fast QD4/QD8/
QD32 and serial-depth QD32; the latter is the terminal evidence gate for whether
the one-producer/64-slot preparation subsystem still earns its code and state.
The rootless report and public-`make test` fixture contracts must mirror that
48-session shape and must print the serial-QD32 paired 95% interval alongside
the three fast-QD intervals, so a harness change cannot silently drop the
de-bloat gate. Report `64f6e8e1890e` measures serial-QD32 async/sync at +4.2%
with paired 95% CI [+2.7,+5.7]%, so the producer lane and 64-slot reservoir stay;
the synchronous-default de-bloat branch is rejected on this evidence. On the same ARM64/NEON
lineage, preserve the `b389204` completion-state result (fast mixed useful
WRITE 60.43 MB/s, async/sync +0.7%, async-minus-sync lower-WRITE requests -12.6
with 95% CI -23.6..-1.6) while recovering the `8a6dd2a` deep-QD direction
(QD8 +74.6%, QD32 +14.9% async/sync). The fully qualified `c07edd9` result is
the regression control: QD8 -8.1% (95% CI -18.1..+1.9), QD32 -16.3%
(-18.6..-14.0), with 58.8/67.8 deadline closes. A candidate is not promoted
because its learned target or deadline counters look cleaner; useful
WRITE/READ, lower bytes/requests and p99 must jointly improve or remain within
the predeclared acceptance envelope. Retained-chain and sampled-tail evidence
may not survive a true worker-idle or hard ordering boundary. The learned
singleton fast-close heuristic is separate: it intentionally survives ordinary
IDLE/DEADLINE closes and is cleared by accepted concurrency or an explicit
ordering boundary.

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

Source coverage must keep dispatched-run READ independence (an empty collector
with an active K=1 run is not a dependency, and window evidence plus the
deadline-after-READ flush require an open window) and the deferred
acknowledgement invariants: deferral only inside the ordered work item, delivery
before any finalize wait and before the work item returns, slot release before
deferral, failed runs acknowledged immediately.

Source coverage must require the ordered `swapz` workqueue to use a bound,
single-active `WQ_MEM_RECLAIM` queue and the `swapz-lz4` preparation workqueue
to use `WQ_MEM_RECLAIM | WQ_UNBOUND`. The ordered authority workqueue remains
single-active and async preparation owns one producer lane regardless of
delta64 policy. The retired `delta64_prepare_workers` runtime selector must
remain absent after two-host K=2 evidence and earlier K=4 regressions closed
the concurrency question. The retired K>1 parallel-tail branch and its live
parallel-start atomic are removed; the historical status field remains fixed at
zero for report compatibility. Predictor scratch allocation remains conditional
on rescue being enabled. The lane owns private input/predictor/LZ4 scratch and
single-writer diagnostics; FIFO admission, global packing, physical WRITE
submission, authority publication and BIO completion remain serialized under
the ordered owner.
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
A direct production-C regression must also populate validated read residency,
perform a non-overlapping one-record planned write, and require the original
page to reread without another lower request. An append-only overwrite may
therefore leave the old immutable physical extent resident, but authority must
point at the new start block/generation and the next logical reread must miss
that stale-range entry, issue lower I/O, and validate the new bytes. Source
coverage must place the planned-write exact-range invalidation after successful
stage/seal and before `write_extent`, with full invalidation retained only for
verify-after-write.


K=1 detachment source coverage must require the restored pre-ID80
depth/backlog predicate
`(count > 4U || READ_ONCE(ctx->preparation_queued) > 0U)`. IDLE and DEADLINE
remain eligible under that same close-reason set. Source tests must reject both
the refuted ID80 `count > 4U`-only policy and the unqualified `count > 1U`
replacement. Exact source `0155a09a0f2e` passes all five owner stages with
this restored predicate, including retained suspend/drain (report
`dc78c9bbffbd`). A future scheduling candidate that fails the loaded
suspend/drain lifecycle gate is rejected before any performance result is
interpreted. No new timer, K>1 slot, preparation lane or SWZ class is permitted.

Work-conserving queue/reservoir qualification must report descriptor-queue
occupancy/high-water mark, prepared-reservoir occupancy/high-water mark,
compressor claimed/completed/discarded work, dispatcher runs, and accepted-work
idle episodes. Source coverage must prove admission performs no unconditional
4KiB copy and that every retained direct upper-page reference has an explicit
lifetime owner until all possible readers are done. The reservoir must be
preallocated/bounded and suspend/drain must return with every descriptor and
reservoir slot released exactly once.

Work-conserving representation qualification must distinguish ordinary RAW
fallback caused by incompressibility from RAW selected because optional
preparation was not ready at a lower-service opportunity. The candidate must
report both counts plus compressed-ready-at-dispatch, discarded-late-preparation
results, accepted-work/no-lower-WRITE idle wall and lower-WRITE active fraction.
The accounting identity must prove that every accepted nonzero WRITE reaches
exactly one terminal representation and exactly one upper completion.

Native/source coverage for an in-flight RAW selection must prove the producer
cannot dereference `dm_per_bio_data` after the upper BIO is released. If the
candidate retains the BIO until preparation drops its reference, loaded
qualification must measure that completion delay and cover suspend/drain with a
producer still active after RAW lower submission. If it instead introduces a
stable preparation job/snapshot, allocation is bounded and precreated, slot
release is exactly once, and teardown drains every producer reference before
freeing storage.

The active mixed-run contract remains compressed-prefix then RAW-tail under the
existing SWZ format. Byte-exact readback must cover all combinations: all
compressed, all RAW, compressed+RAW in one lower run, RAW chosen while
compression is still active, duplicate logical writes, PREFLUSH/FUA, same-page
read-after-write, injected lower failure and ENOSPC/GC pressure. RAW selection
may not bypass a barrier, same-page predecessor or capacity reservation.

Product evidence must be Pareto-aware rather than require maximal compression.
On slow/SD models, reject a candidate that materially loses established useful
service or lower-I/O savings merely by converting prepared work to RAW. On
SATA/NVMe models, some increase in lower bytes/requests is acceptable only when
accepted-work idle wall falls and useful service/p99 materially improves versus
the same-source current policy. K>1 remains closed unless ready-run wait becomes
material after the K=1 scheduler is work-conserving.

Source-contract maintenance must follow the same standards co-change rule as
production implementation work. When an implementation invariant moves between
owners (for example, PACK_READY closure from write admission to the serialized
worker), contract assertions must move with that ownership in the same
standards-backed change rather than preserving historical body-local syntax.

ID83 dispatcher refinement contracts must prove all scheduling boundaries:
ordered RAW forcing requires an actually idle lower-WRITE path, stays within the
first eight-record pressure hand, requires at least eight accepted records
across the active batch plus unclaimed preparation queue, and for retained
operation requires an effective learned/sampled target no larger than the hand.
Native policy coverage must prove non-retained dispatchability, retained targets
at/below eight, rejection above eight, sampled-target override, and a zero-hand
fail-closed case. QD1/QD4 must not be forced RAW by transient two-record
backlog. While an already-accepted plain
WRITE remains, the eight-record pressure hand may not split the FIFO below the
effective learned/sampled target merely because the next representation is
unready. Only after the worker proves local and incoming accepted FIFOs dry and
no K=1 lower WRITE remains active may a below-target `SERVICE_DRY` close
occur at the four-record floor, including RAW/compressed mixes and oversized
sampled targets. Pure-WRITE two/three-record tails retain their old fence. A one-record window always retains the
pinned ordinary deadline. A mixed-wave sampled tail at count two/three is
different: a READ already serviced by the worker or an accepted non-WRITE
boundary in the sampler proves the current tail finite, so that exact target may
close without a timer. Producer ownership still does not make RAW dispatchable
before the stable snapshot completion.

Status/replay/reporter qualification must retain
`accepted_work_lower_idle_events/ns` and the four-way retained-open-batch
attribution
`undersized_batch/worker_unscheduled/preparing_head/no_ready_work`; their timed
interval deltas must sum exactly to `accepted_work_lower_idle_ns`.
`accepted_work_lower_idle_post_lower_ns` is a separate callback-to-publication
diagnostic and must not be included in that conservation sum. PACK_READY
telemetry must attribute below-target work-conserving packed closes to
`SWAPZ_PACK_CLOSE_SERVICE_DRY`, never BURST_TARGET. Native window-policy tests
must cover 1..3-record retention, dry compressed+RAW closure at each count 4..7
below a larger learned or sampled target, an accepted plain-WRITE follower blocking that
floor, the unchanged eight-record active-wave hand, sampled-tail override, and
unchanged non-retained behavior. Source contracts must retain four-record
K=1 detach eligibility and first-three-inline LZ4 protection, without
weakening producer snapshot/terminal-state ownership. Loaded qualification remains authoritative
for actual scheduler timing, byte geometry, useful throughput and p99.


Only a successful PACK_READY continuation may arm post-I/O admitted-tail
sampling. Other retained chain continuations such as duplicate/full or
already-accepted zero/raw interruption may carry bounded service/count evidence
within the same worker burst, but must keep
`pack_close_pending_tail_sample` false so they cannot infer a residual tail
from a non-PACK close.


Nonblocking preparation-slot qualification executes the shared production
mask helper with C11 atomic shims. The shim must model Linux atomic_read() as
relaxed and provide a separate acquire load for prepared-state publication;
tests must not accidentally strengthen the production memory model. Exercise
all 64 slots, exhaustion without mask mutation, bit 63, release/reclaim,
rejected-claim cleanup and concurrent producer/consumer payload reuse. Native
stress does not prove the Linux memory model or loaded BIO lifecycle. Source
contracts also require that an unclaimed ordered FIFO head is removed from the
preparation queue before the ordered worker may return; merely queueing producer
work is not an ownership handoff. Source contracts require a bounded claim before
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
alone may wake on one queued descriptor, but source qualification must
distinguish synchronous lower service from a detached K=1 run. Only synchronous
lower WRITE service may make the producer claim the FIFO head. While detached
K=1 is active, the producer must leave a singular head for ordered inline steal,
claim only a true tail, and bypass idle tail-credit gating without changing
mapping/publication/completion ownership. Source contracts must pin that
distinction to the existing in-flight K=1 state rather than a new mapper-visible
busy flag. Lower READ service must not wake or switch the producer to head-first
claiming. The compatibility status fields
`prep_lower_read_overlap_starts` and `prep_lower_read_overlap_ns` must remain
parseable and exactly zero. Owner evidence must re-run the existing
persistent-worker QD1/4/8/32 matrix; reject the candidate if QD8/QD32 loses its
confirmed async advantage or if QD1/QD4 pay material producer-wakeup cost.

The retired dry-close timer answered its bounded scheduling question and is no
longer production telemetry. The active starvation probe is observational:
`preparation_queued` counts unclaimed preparation descriptors exactly under
`queue_lock`; every synchronous lower WRITE records queue depth and whether it
is nonempty immediately before `dm_io()` and immediately after it returns.
The lower-WRITE queue probe itself must not grant credits. Lower READs may use
bounded read fan-out/coalescing and may contribute ordinary ordered-service tail
credit, but they must not directly wake the preparation lane, publish authority,
submit WRITE I/O, extend retention, or alter upper completion ownership.

Native `window-policy` coverage keeps the finite burst/tail readiness rules,
while source contracts prove admission no longer owns PACK_READY and the
post-K1 worker path samples the pending tail before re-evaluating a dry accepted
FIFO and before arming `retention_timer`. The compatibility
`pack_close_burst_admission` counter remains parseable during this evidence
cycle but must be exactly zero for every current swapz timed arm.

The first owner-qualified ID83 dispatcher baseline used source
`91c2cb2edb1e` / report `aacf96c02325`. That run passed correctness,
lifecycle, fault and resource-pressure qualification, but fast-media scheduling
was not promoted: fast mixed async-minus-sync useful WRITE was +3.5% with a 95%
CI of -0.2..+7.2 while lower WRITE requests regressed by +869.4
(+796.2..+942.6), and fast sustained QD32 async-minus-sync was -9.8%
(-14.2..-5.5). That result established the requirement for the later refinement
to reduce request inflation and recover deep-QD service without materially
regressing the qualified SD result, lower bytes, READ service/p99, CPU/RAM/GC
or correctness. Accepted-work lower-idle wall remains required beside existing
ready-wait/preparation counters; K>1 remains closed while K=1 ready wait stays
zero. The current qualified ID83 state is recorded in the Current qualified
baseline above and in the ROADMAP decision record.

These scheduling rules are architecture-neutral. The single public `make test`
command remains unchanged on SSE2, AVX2, AVX-512 and NEON hosts; existing
architecture-specific SIMD byte-equivalence, instruction-shape and runtime
timing qualification remains mandatory and is not bypassed by this change.

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


### Immutable one-slot lower-I/O qualification

A submitted WRITE run is immutable until definitive lower completion and ordered
publication. Completion callbacks must never observe reused packed bytes,
transaction snapshots, batch hashes, upper-BIO pointers or ordering state.

The active collector and the one streaming run are separate ownership domains.
Collection may perform zero detection, compression and payload CRC while the
previous run is in lower I/O; freezing a run forbids further mutation. Do not
split a well-packed wave merely to manufacture overlap.

Production now has one lower-WRITE slot. The former depth-two allocation/append
path and routine K=1/K=2 A/B are removed. Source qualification must prove the
fixed one-slot bound, immutable ownership, ordered publication, and complete
drain at barriers, suspend, teardown and failure. Any future K>1 design is a new
architecture experiment and must re-establish same-page ordering, independent
run ownership and FIFO publication from first principles.

Latency-sensitive READs still bypass batching when lower I/O is idle. Busy-time
READ fan-out/coalescing uses private scratch and must respect same-page
dependencies against collected/frozen/in-flight writes.

The fresh post-ID107/ID108 K=2 trial (ROADMAP ID110) reached observed depth
two but did not establish a useful-service win in adjacent three-repeat
K=1/K=2 development blocks. It is not owner qualification. Current source
contracts and benchmark policy must continue requiring the fixed one-slot
implementation. Any later overlap claim must record actual lower depth,
absolute useful READ/WRITE, p99, independent lower bytes/requests and raw
control drift; a configured depth of two or a busier device is insufficient.
Remove rejected experimental selectors, allocations and hot-path branches.

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

Native report-publication tests that create temporary Git repositories must use
`git init --object-format=sha1` (and the equivalent explicit SHA-1 form for
bare origins). The GitHub repository and current report/provenance schema use
40-hex SHA-1 object IDs, so test sandboxes must not inherit an operator's
`init.defaultObjectFormat` or `GIT_DEFAULT_HASH`. Supporting SHA-256
repositories is a deliberate report-schema migration, not a fixture-side
autodetection change.

### Generated report versus tracked source cleanliness

`test_results.json` is the one generated overwriteable evidence file and is
not tested source. The unprivileged loaded-test parent excludes only that exact
root path from its tracked/staged source-cleanliness check before crossing the
privilege boundary. This permits a previous local report to remain until the
current run finishes, including after an earlier publication failure. Every
other tracked or staged change still blocks loaded qualification before
module/device work.


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


### Privileged helpers must not access Git metadata

All branch, source-identity and tracked/staged cleanliness checks run in the
unprivileged loaded-test parent before the first privilege boundary. The tested
source SHA is then passed explicitly to each privileged device helper.
Privileged helpers must not invoke Git at all and must not create temporary
session directories inside the checkout. Their session logs/results live under
the system temporary directory.

Before the first privileged child, the parent records the ownership/mode of the
repository administration directory and index and requires both to be writable
by the invoking user. After every privileged child it verifies that both
identities and writability are unchanged. Any change fails qualification
immediately. `GIT_OPTIONAL_LOCKS=0` is not an acceptable substitute for this
boundary because a root-side Git command must never be allowed to own or
replace operator Git metadata.


### Explicit lower queue geometry

Performance null_blk models pin and reread queue geometry before power-on. The
slow profile is blk-mq queue_mode=2, submit_queues=1, hw_queue_depth=1. The
fast profile is queue_mode=2, submit_queues=1, hw_queue_depth=64. The report
records these values with bandwidth and timer latency; mismatch is incomplete.
Loaded correctness smoke also uses depth 1. These are synthetic queue models,
not literal SD/HDD/SSD/NVMe protocol emulation.

Routine qualification preserves those two historical profiles for continuity.
A separate directional QD32 service-envelope sweep must additionally run exact,
allowlisted null_blk tuples for modern SD (100 MiB/s, 500000 ns, submit_queues=1,
hwq=4), SATA SSD (500 MiB/s, 100000 ns, submit_queues=1, hwq=32), Gen4 NVMe
(6500 MiB/s, 25000 ns, submit_queues=4, hwq=64) and Gen5 NVMe (12000 MiB/s,
14000 ns, submit_queues=4, hwq=64). Arbitrary cap/latency/queue combinations
must still be rejected before privilege. Each envelope runs one production
async mixed off/swapz comparison and one positive-delta64 write-only off/swapz
comparison. These rows are directional bottleneck evidence and do not replace
the matched fast-model qualification intervals.

The four modern service envelopes must use the test-only native-C replay
engine for both raw/off and swapz arms. Python remains the safety/orchestration
authority: it validates the immutable trace, opens and positively identifies the
owned target, captures lower/kernel/host boundary counters, and performs the
final byte-exact image oracle. The native helper inherits only those already
validated target and fixture file descriptors; it must not discover, open or
authorize a block device itself. It pre-creates exactly QD worker threads,
finishes warmup before a READY/GO measurement gate, preserves the existing
fixed-wave ordering for mixed traces and disjoint ordered lane ownership for
persistent write-only traces, verifies every timed READ before lane reuse, and
includes the required final `fsync` in measured wall time. Helper/thread
startup, trace staging and latency-result serialization remain outside the
timed interval. The helper is an internal test binary under `build/tests/`;
it creates no new public test command.

Modern-envelope report parsing must require `replay_engine=native-c` for both
arms and reject silent fallback to Python. The historical 10/80 MiB/s
qualification remains on the existing Python replay so its matched baseline is
not changed by this harness experiment. Rootless qualification must exercise
both native mixed-wave and native persistent-write modes on regular files and
prove the same immutable-plan/final-image contract. Native replay changes
submission overhead only; the envelopes remain synthetic `null_blk` evidence
and never become physical-media saturation claims. Rootless Make-interface fixtures that synthesize these
rows must emit the same marker on both raw/off and swapz arms; otherwise the
fail-closed parser must reject the fixture exactly as it would reject stale
loaded evidence.

For an offered-QD-limited diagnostic, the analytical unmerged-4KiB latency
ceiling uses
`min(offered_qd, submit_queues * hw_queue_depth)`, not hardware depth alone.
Reports must retain lower-WRITE byte/request speedups, useful-WRITE speedup and
bandwidth-opportunity capture `(useful_speedup - 1) / (byte_speedup - 1)`
when byte speedup exceeds one. They must also retain sampled lower-WRITE
peak/time-weighted depth and the timed swapz K=1 ready-window wait,
preparation-handoff wait, lower-WRITE and lower-READ preparation overlap,
lower-run occupancy,
`pipeline_post_lower_wall_ns` callback-to-publication/release hold, commit
non-I/O, planner, pack, publication and final publication-CRC attribution. Those diagnostics decide which architecture question is eligible to reopen.
Ready-window wait identifies a genuine K=1 successor blockage; post-lower hold
identifies time after device completion before the sole immutable slot is
released; preparation wait identifies producer/ordered handoff starvation.
They are not themselves a performance-promotion verdict and must not alter
runtime policy.

Each timed benchmark arm samples only its positively identified owned lower
device's `/sys/block/<disk>/inflight` counters. The sanitized report records the
target sampling interval, achieved sample count, initial/last sampled
READ/WRITE depth, sampled peaks and sample-and-hold time-weighted means.
Sampling is observational and is not an exact per-request trace; the achieved
sample count stays visible so sparse evidence cannot be mistaken for complete
queue history. Lower inflight sampler thread startup and shutdown lifecycle
synchronization bounds provide 2.0s timeout headroom with single-budget stop
deadlines and lock-free thread state and frame diagnostics so any stall pinpoints
the exact blocking location without secondary deadlocks or masking test regressions.

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
`device_model` dictionaries compare all six fields. Modern service-envelope
fixtures also carry `replay_engine=native-c`; a missing or different engine
makes the directional envelope matrix inconclusive.


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
and their sum must equal `win1_pack_ready`; ID50 must not make sub-four singleton tail
closes reappear under the read-bypass or wave bucket.

### Retained-singleton and PACK_READY regression contract

The retained policy is settled; qualification protects the current behavior
rather than rerunning the old optimization sequence.

- **ID50 remains active:** a sampled admitted tail of one may update learned
  burst width but cannot arm a one-record PACK_READY target. It sets
  `retained_single_tail_deferred`; tails of two or more may arm their exact
  finite target. The second admitted WRITE resolves the deferral.
- **One deadline only:** a deferred singleton uses the ordinary first-record
  retained deadline. ID53's short cutoff/watermark/timer is rejected and must
  remain absent.
- **Lifecycle accounting:** timed deltas must satisfy
  `D == C + DL + I + O` for deferrals, companions, deadline, idle and other
  clears. Deadline/idle subsets may not exceed their matching one-page close
  counters. Missing or inconsistent fields fail qualification.
- **Timing/service telemetry is observational:** companion/deadline age bins
  must conserve to their terminal counts; lower-done/read-bypass/both are
  bounded subsets. These counters do not authorize an early close.
- **PACK_READY cause telemetry is observational:** tail-target, burst-target and
  service-dry primary causes must conserve exactly to PACK_READY closes. Burst
  site/target/count bins and overshoot must conserve to the burst-target subset.
- **ID56 tail sampling remains observational:** the six 0/1/2+ crossed-with-
  active/idle buckets conserve to `pack_tail_samples`.
- **ID57 remains rejected:** no K=1-busy PACK_READY suppression, zero-tail hold
  state or completion-aware carry into a later wave may reappear. Source tests
  assert absence; reopening requires a new ownership model, not another tuning
  constant.
- **Worker CPU attribution stays diagnostic:** scheduler-updated
  `ordered_worker_cpu_ns` and `prep_worker_cpu_ns` may omit pending execution
  or charge earlier execution at callback boundaries. They are not guaranteed
  CPU bounds or total CPU. The retired read-helper compatibility CPU field remains zero. Keep
  ordered/preparation LZ4 and explicit copy wall counters separate.

Do not add another singleton timing policy merely because these counters remain
available. The ROADMAP evidence table is the reopen authority for IDs 50-57.

### ID36 low-RAM plus heavy-CPU qualification

ID36 is a release gate for default-on asynchronous preparation, not a
throughput-promotion benchmark. The loaded stage runs one fast-model QD32 async
OFF/swapz pair with a fixed short trace (128 warmup + 2048 measured operations)
and the normal packed byte-exact readback inside a dedicated cgroup-v2 domain,
while a separate helper faults 576 MiB of anonymous memory and runs twice the
online CPU count of integer burners, capped at 32. The shorter trace preserves
mixed QD32 concurrency while preventing arbitrary benchmark-duration timeouts
from being mistaken for a forward-progress failure; the per-candidate replay
timeout under `--resource-pressure-short` remains bounded at 280s. Because the
OFF and swapz candidates run sequentially, the pair watchdog is 840s
(`2 * 280 + 280`: both replay bounds plus one replay-bound orchestration
allowance for the private barrier, pressure-throttled target setup, comparison
and teardown), and the top-level ID36 helper watchdog is 960s. The extra parent
time does not extend either replay's 280s forward-progress limit. Parent bounds
must remain strictly outside their bounded children; a parent timeout may not
preempt a candidate that is still within its own forward-progress limit. The pressure-only mixed-QD32 replay uses the existing native-C wave helper
with pre-created worker lanes and fixed event/latency buffers, instead of
creating Python Futures/WorkItems for every wave above `memory.high`. It
retains the identical 128+2048 immutable read/write trace, direct I/O,
per-operation byte checks, timed workload boundaries, final image oracle and
280s timeout, and requires the native helper to exist before entering the
owned cgroup. The pressure-only packed-read verifier still uses 32 persistent
Python lane jobs and reusable barriers/results for population plus both 4MiB
read orders, eliminating per-I/O Future/work-item allocation while keeping
QD32, byte-exact verification, p99 and lower-I/O boundaries unchanged. The
ordinary benchmark path is not switched to this replay mode. The cgroup sets
`memory.max=896MiB` and `memory.swap.max=0` when supported. The helper first
establishes the resident baseline without memory.high throttling; immediately
before releasing the benchmark, `memory.high` becomes the measured ready-state
`memory.current` plus 64MiB. The host must
have at least 1 GiB MemAvailable before this destructive-to-performance but
RAM-only stress begins; otherwise qualification is BLOCKED rather than silently
weakened.

The owned pair first creates and fully faults both 64MiB memory-backed
`null_blk` devices outside the ID36 cgroup. It then migrates its benchmark
process into the cgroup, proves that membership, and stops at a private barrier.
Only then does the pressure helper start niceness-10 CPU burners and fault its
anonymous resident set in the same cgroup. The burners are forked before the
576MiB mapping is created, so they do not inherit that mapping's COW page-table
footprint. The backing pages therefore do not consume the cgroup's pressure
budget. After readiness, the qualifier measures the complete cgroup charge and
adds exactly 64MiB of working headroom for target/replay memory. Evidence
counters are baselined only after that high watermark is installed, so helper
startup cannot satisfy the required positive `memory.events high` delta. The
barrier still guarantees
that module insertion, target construction, replay and teardown execute under
reclaim/CPU contention. Lazy null_blk page allocation is not the test subject.
The pressure helper must reach readiness with at least the requested resident
memory charged to the cgroup and remain alive through benchmark teardown.
Qualification
requires a positive `memory.events high` delta, positive CPU PSI `some total`
delta, zero `oom` and `oom_kill` deltas, and the normal owned-pair byte-exact
verification/teardown to pass with `async_prepare=1`.
The test uses only positively owned `null_blk` backings and never authorizes
physical media or active swap. Performance under this gate is observational:
record it, but do not tune a scheduling threshold from one pressure run.

Rootless contracts must lint both the pressure helper and shell wrapper, and the
loaded report parser must require the exact `PASS_ID36_RESOURCE_PRESSURE`
marker. Missing cgroup-v2 controllers, insufficient host safety headroom,
missing PSI, an OOM event, a dead pressure helper, or failed owned-device
teardown blocks release qualification.

### Bounded concurrent READ qualification

The retired `swapz-read` helper workqueue remains absent. Ordered-worker
private-slot lower-READ fan-out is now fixed-on production infrastructure.
The final five-pair fast-model decision at source `11fbc839...` ran with
`read_coalesce=0` and established repeatable useful-service and tail-latency
gains: mixed WRITE/READ throughput +17.9% (95% CI +17.2..+18.5), mixed READ
p99 -48.7%, packed sequential READ throughput +67.9%, and seeded-random READ
throughput +101.8%. The off arm executed zero async batches/slots and the on
arm exercised real fan-out; raw-control drift overlapped zero. The
`parallel_reads` module parameter and routine A/B are retired. Keep the
historical parser so older reports remain readable, but current loaded
qualification must report `parallel_reads_enabled=1`.

ID63 remains the adjacent request-efficiency experiment. The loaded test keeps
exactly ten SSD_EMULATED and ten SD_EMULATED sessions in the fixed
counterbalanced sequence while varying only `read_coalesce=0/1`. Both arms
must report `parallel_reads_enabled=1`. The loaded replay snapshot must
preserve `parallel_read_async_batches` and `parallel_read_async_slots` in
the same measured C-counter record consumed by the report parser. The merge-off
arm may therefore record those fan-out counters, generic parallel pairs and
distinct-extent service, but every ID63 adjacency,
coalesced-range and coalescing-skip counter must remain zero. The merge-on arm
uses the identical fan-out fallback after any non-coalescible prefix. A
coalescible adjacent subset is also required to fall back when it does not cover
the complete bounded fan-out batch (up to eight distinct extents, or reaching
the eight-block scratch cap); this prevents synchronous ID63 service from
stranding unrelated independent READs that the fixed-on fan-out path could
otherwise submit together. A merged span retaining at least two adjacent
extents remains eligible when partial cache residency covers companion extents.
A full eight-slot chain
may leave additional local READs for the next bounded worker iteration. Three-host
cap evidence is sufficient to fix the maximum coalesced span at eight blocks:
8 materially improves serial sequential service versus 4 on all three hosts,
while fast-model comparisons do not establish a smaller cap as better. The
runtime cap selector and routine 2/4/8 sweep are retired.
Rootless source/build contracts assert that retired production selectors and
their routine loaded markers are absent, while fixed compatibility telemetry
continues to report the selected production values. The private benchmark
helper must not retain retired selector variables or command-line suffixes.
Its delta64 second-pass acceleration and independent-READ defaults remain
separate pinned controls so retiring ordinary LZ4 tuning cannot alias them.

Every packed READ pass remains 4 MiB/1024 byte-exact verified pages. Reports
must show sequential and seeded-random useful READ MB/s, p99, lower bytes and
lower requests, plus paired two-sided Student-t 95% confidence intervals for
throughput, p99, lower bytes and lower requests. Request reduction alone is not
a performance win.

No `swapz-read` workqueue is permitted. Independent missing ranges are
submitted asynchronously into disjoint preallocated slot scratch, all selected
submissions happen before the ordered worker joins any slot, and each callback
only signals lower completion. The ordered worker performs generation,
descriptor and payload-CRC validation, copies the logical page and then may ACK
that slot immediately. If a later slot fails, already ACKed validated slots are
not retroactively failed; only still-owned BIOs fail closed. Shared cache
absorption remains ordered-worker-only.

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
The terminal loaded ID72 experiment on owned RAM null_blk has been completed,
demonstrating that circular FIFO allocation naturally balances segment opens
without requiring O(segments) least-open scans. Circular allocator fairness
is retained as the canonical policy; the optional switch is removed.

### ID72 skewed-churn logical-open balancing decision

The terminal promotion/removal experiment was executed using the owned-RAM
target and the predeclared medium-compressibility workload. Exactly 2,867 of 4,096
logical pages (70.0% occupancy) were seeded: 2,294 cold pages remained untouched
and 573 hot pages received 40,960 deterministic writes with an fsync every 256
writes. All seeded cold pages and final hot pages were verified byte-for-byte.

Across five counterbalanced pairs on owned RAM, baseline circular allocation
yielded min 0, max 4, sum 172 across 64 segments (spread=4). Least-open
scanning achieved an identical spread of 4 across all five runs (0.00% spread
reduction, 95% CI [0.00, 0.00]), while regressing write p99 latency by +9.93%
(+18.0 us) due to scanning dead segments on every allocation.

Per the predeclared protocol (spread reduction < 20% and >5% guard regression),
`logical_open_balance` was removed and circular allocator fairness retained
as the sole, canonical policy. Logical-open counts remain allocator fairness
telemetry, never NAND P/E evidence.



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

Current rescue emits DELTA64_SHUF8 (delta64, eight byte planes, LZ4).
Require byte-exact scalar/SIMD shuffle, unshuffle and combined reconstruction,
legacy plain-delta64 decoding, all valid map encodings at index 63, rejection
of reserved flag combinations with a recomputed valid metadata CRC, and GC
preservation of payload/encoding. Execute each ISA on supporting hardware;
ARM64 runtime coverage and x86 assembly inspection do not qualify x86 runtime.
Keep offline timings, loaded positive-fixture pairs and the full owner matrix
distinct. Historical plain-delta64 timings do not measure the new path.

The delta64 transform unit is one 4KiB logical page, never a whole packed
extent. Direct production-C coverage must prove ordinary LZ4 and delta64 records
share the unchanged 16-byte SWZ record size, decode the encoding bit exactly,
reject reserved header flags, and preserve payload CRC validation.

Both write owners must bypass rescue when the read-only, default-on
`delta64_rescue` module parameter is loaded as 0. Snapshot it at construction
and allocate predictor scratch only when enabled. The bare-load smoke and the
packed-placement reload must assert `delta64_rescue=1` and nonzero
`delta64_eligible` (the classifier scored ordinary oracle pages); adoption is
content-dependent and not required there. Standard mixed and write-only
sessions must report the production default (`PRODUCTION_DELTA64_RESCUE`); the
rescue A/B off arm, the medium-mixed envelope control and retired LZ4/depth
A/Bs pin rescue off. Only an explicit `--delta64-rescue` positive-fixture
session must show classifier passes and adoptions. Encoded reads retain inverse
support and fail closed if their scratch is missing.

The default-on classifier has two production routes and runs before ordinary LZ4.
Score >=24 pages try delta64 plus the rescue LZ4 first; candidates <=2024 bytes
may be direct adoptions with no ordinary-LZ4 baseline, while larger candidates
fall through to ordinary LZ4 and require a strict size win. Lower-score pages
run ordinary LZ4 first; when the engine identifies a lower uniform-payload
packing limit across 4/8/16KiB extents, threshold 16 may route a second-pass
candidate that must cross that limit and remain strictly smaller. Neither route
runs while rescue is disabled. Source
`174d42eb7135899d4bc0acb22ea82f5be1317f5f` is owner-qualified with a
positive-content rescue A/B; representative swap-content promotion remains
open. Shared production-route screening evidence must be split
across compact Markdown tables so every rendered console line remains below 96
characters. Metadata payload-copy counters exclude cache insertion copies and
directory lookup counts exclude scratch/extent-cache hits.

Capture every production `delta64_*` counter in drained, timed mixed and
sustained-write snapshots. Missing fields are unavailable evidence, not zero
activity. Require adopted <= attempts <= classifier passes <= eligible; the four
score bins 0-7, 8-15, 16-23 and 24+ must sum exactly to eligible; 24+ scores are
a subset of classifier passes; packing-adopted <= packing-cliff-crossings <=
attempts; packing-adopted <= packing-attempts <= packing-eligible <= eligible;
packing-adopted <= LZ4 rescues; adopted = RAW rescues + LZ4 rescues + direct
adoptions; and first-LZ4-skipped >= direct adoptions. Predictor-first direct
adoptions have no ordinary-LZ4 baseline, so they do not claim baseline-relative
payload-byte savings; total/split payload savings remain the RAW/LZ4 rescue
buckets. Reject resets and impossible per-rescue savings. The loaded replay
snapshot and the report validator must enforce the same accounting.

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

Three-host loaded evidence closes the ordinary first-pass LZ4 acceleration
experiment. Acceleration 4 reduced compression wall time but did not produce a
repeatable service gain; the AVX-512 host showed a small significant throughput
loss and p99 increase, while SSE2 was unresolved and ARM64 was too noisy to
promote. Production ordinary LZ4 is therefore fixed at acceleration 1 and the
runtime selector plus ten-session loaded 1/4 A/B are retired. The fixed ordinary
acceleration is not stored per target; status emits the compile-time policy
value. The deterministic native 1/2/3/4 sweep remains only as low-cost
codec/geometry regression evidence; it is not a promotion gate. Delta64's
second LZ4 acceleration is a separate rescue policy (default 4) and remains
independently qualified.

Source-contract qualification must pin the safety boundaries of the optimized
paths: generic-planner duplicate protection remains enabled; only the
prevalidated production planner sets the uniqueness fast flag; cached metadata
uses descriptor-only lookup only behind a validated-source test; metadata
sequence is checked before payload lower I/O; provisional coalesced blocks
cannot be published as validated cache; publication preflight contains no
global GC mutate/restore loop; and paused-batch hashing covers the active
transaction prefix.
Source-contract body extraction must recognize the kernel fixed-width scalar
return types used by production hot paths, including `swapz_u8`; pointer-return
helpers may be asserted from their bounded source structure rather than
expanding a scalar-body parser. Contracts should follow the current semantic
owner rather than preserve retired source spellings.

The ID73 scalar hot-path follow-up is semantics-preserving qualification, not a
new runtime policy. Direct production-C/native tests must continue to cover all
1/2/4-block planner outputs, duplicate-page rejection, RAW/compressed batched
fallbacks, malformed SWZ descriptors, publication accounting failures, GC
sidecars and private READ slots. Source contracts pin the two-block fit shortcut,
equal-take class pruning, deferred RAW pre-scan, reverse bounded publication
delta lookup, mapped-READ O(1) precheck, metadata-cache null guards and the
monotonic payload-bound validator. W=1/W=2 builds remain mandatory. Because
these paths are architecture-neutral C, every supported host runs the same
`make test` interface; architecture-specific SIMD qualification remains
unchanged.

The next ID73 structural pass must keep public generic defenses while proving
the production-only proof reuse. Native publication coverage must construct a
metadata-CRC-valid extent containing duplicate logical descriptors through the
unique append helper and prove both public `swapz_validate()` and
`swapz_finish()` reject it without publishing any mapping. Batched aggregation
must continue to prove duplicate windows fall back to the sequential checked
path, failed/short lower runs publish nothing, and successful replay remains
byte-exact.

Source contracts must pin that `swapz_finish()` calls
`swapz_validate_metadata_crc()` rather than the full validator, checks exact
payload adjacency in Phase 1, and still compares every descriptor to the
staged transaction. They must pin that unique staging retains logical-range and
generation-overflow checks, and that the authority-owned active-transaction
pointer is used only after `swapz_batch_resume()`. External transaction
mutation tests remain mandatory and must continue to return `-ESTALE`.
When a public wrapper delegates to a private production policy helper, source
contracts for allocator/transaction invariants must inspect the helper that owns
the behavior rather than require the old wrapper body spelling.

The existing native authority-throughput test also reports same-host supporting
microbenchmarks for a 64-record full validator versus metadata-CRC validation,
and checked versus caller-proven-unique 64-record append. These measurements
are CPU diagnostics only; they do not replace loaded, matched lower-I/O,
throughput, tail-latency, CPU/PSI and byte-exact qualification.

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
batch, and report lower requests, useful throughput and p99. The fixed
eight-block cap is not stored per target; status emits the compile-time policy
value. The conservative 3+ full-extent counters remain opportunity evidence,
not proof of an active merge.

Publication tests must continue to inject malformed siblings and GC-accounting
underflow/overflow and prove all authority arrays are byte-for-byte unchanged
on failure. Successful multi-record publication must prove live-record,
mapped-page, GC-score and page-list totals equal a slow recomputation after the
aggregate fast path.


Routine qualification no longer repeats the lower-WRITE depth 1/2 A/B: the
completed idle SSE2 and AVX-512 five-pair cycles found no throughput/latency
benefit. Production is fixed at depth one; the second-slot allocation, append path,
ring indices and modulo bookkeeping are removed rather than retained as dormant
diagnostic code. The target owns one inflight lower-WRITE object, with no
ring head/tail state or modulo bookkeeping. Source qualification names this
single-owner contract explicitly. The fixed depth is not stored per target;
`write_pipeline_depth=1` status remains compatibility telemetry only. Git
history preserves the experiment if future real-device evidence supplies a
specific reason to revive it.

Predictor-first delta64 telemetry must distinguish direct adoptions from
baseline-measured RAW/LZ4 rescues. The rescue A/B continues to pin
`delta64_lz4_acceleration=4` and K=1.


Physical backing is outside the ordinary RAM-backed qualification matrix.
Rootless qualification must verify that the administrative formatter refuses
non-block-device inputs without modification, while source contracts verify
the opt-in superblock gate, reserved data offset, and exclusion of block 0 from
all data/discard paths. Exact-current-main must still pass ordinary `make test`
before any physical-media evidence is considered.

Capacity-exhaustion evidence must preserve committed reads: a write may return
`-ENOSPC`, but `ctx->failed` must stay clear unless a separate integrity or
lower-I/O error occurs.


### Alpha.29 work-conserving dispatcher qualification

The public command remains exactly `make test`. Native qualification exercises
the production PREPARING/READY/RAW_SELECTED atomic race. Source contracts require
the stable `raw_bytes` snapshot, two-reference slot ownership, producer BIO
access ending before `preparation_snapshot_ready`, and worker-owned
eight-record/dry-tail dispatch.

Loaded qualification retains existing byte-exact, fault, GC, PREFLUSH/FUA,
resource-pressure and suspend/drain gates. Timed arms additionally require
parseable hand/dry-close, RAW-not-ready, compressed-ready, raw-ready,
late-result-discard, ready-reservoir and slot high-water counters. Drained
current-ready/current-slot counts must return to zero.

Performance is a service tradeoff: SD must retain useful service and material
lower-I/O savings, while SATA/NVMe may spend additional lower bytes/requests
only when useful throughput or p99 improves. K>1, more than 64 reservoir slots
and wider preparation remain closed until the new counters prove pressure.


Alpha.29 legacy-path correction: the stable RAW snapshot completion is not the
same as optional preparation completion. Each prepared slot therefore owns a
separate `result_ready` completion with the same refcounted lifetime as the
slot. The ordinary bulk path may choose RAW from PREPARING after snapshot
publication; per-extent/verify-after-write paths instead wait on the slot-owned
result completion and retain their pre-alpha.29 representation behavior. The
producer must never signal a per-BIO completion after
`preparation_snapshot_ready`, because the upper BIO may already have completed.


The prepared-reservoir current gauge must never transiently underflow. Producer
code charges `preparation_ready_current` before publishing a READY state, then
rolls that charge back when RAW_SELECTED won the state race. The high-water
mark is updated only after a successful READY publication. This ordering is
telemetry correctness only; it must not influence representation selection.


Alpha.29 source qualification follows ownership after the refcount split:
`swapz_release_prepared()` must clear the per-BIO pointer and delegate to
`swapz_prepared_put()`; only the latter may derive the fixed slot index and
return the final reference to the free mask.


Rootless architecture coverage is continuous on both x86_64 and ARM64. The
production-C workflow runs the same native suite on `ubuntu-24.04` and
`ubuntu-24.04-arm`; x86 therefore compiles/exercises the SSE2, AVX2 and
AVX-512 native predictor objects while ARM64 compiles/exercises NEON. The
compile-only W=1/W=2/normal module build runs on both architectures as well.
This CI matrix does not replace loaded owner qualification: the single public
`make test` remains authoritative on the actual owner host and selects the
same architecture-specific native backend from `uname -m`.


### Loaded-stage observability and hard bounds

The retained-suspend lifecycle oracle sets a 64 ms retention override on its
owned RAM-backed `null_blk` mapping so an observer can sample the open window
on slower hosts. The production retention ceiling stays 4 ms; no benchmark arm
may inherit the lifecycle override. The loaded shell marker, native interface
fixture, report-parser predicate and synthetic parser regression must all
agree on 64 ms. The missing-marker regression must remove the actual fixture
line and require `INCOMPLETE`, never pass vacuously after a failed replacement.

The public `make test` command must never appear to hang silently during its
privileged fifth stage. `run-tests.py` therefore streams the captured
`test-loaded.sh` output live while retaining an identical in-memory copy for
the existing report parsers. The child harness already emits bounded
`START_*/PASS_*` phase markers; those markers are now user-visible as they
happen. Live terminal output is deliberately filtered to phase transitions and
`FAIL:`/`BLOCKED:` diagnostics. Full child stdout, including status snapshots,
JSON benchmark records and detailed evidence counters, remains captured verbatim
for report parsing but must not be echoed line-for-line to the operator terminal.
Retained synthetic write/flush fault PASS markers remain visible as phase
completion even though their marker prefix is not `PASS_LOADED_`.

Every top-level privileged helper invoked by `test-loaded.sh` also has a
root-owned outer watchdog in addition to its internal operation/replay
timeouts. Preflight is capped at 60s, the loaded smoke/lifecycle helper at 600s,
each owned-RAM benchmark pair at 720s, and the ID36 resource-pressure helper at
960s. ID36 additionally keeps its internal 840s pair watchdog and two 280s
per-candidate replay watchdogs. The watchdog runs inside the authorized root shell so it can terminate
its privileged descendants and still execute ordinary helper cleanup. An outer
watchdog expiration is BLOCKED/nonzero, never PASS and never silently retried.
Do not weaken these bounds to hide a kernel forward-progress defect.

The bounded privilege wrapper must preserve the existing shell-helper execution
contract: private loaded helpers are invoked through `bash` inside `timeout`, not
executed directly. Their Git executable bit is not an authorization or safety
boundary. A watchdog refactor must not silently turn a readable private helper
into an `EACCES` failure before its own validation and cleanup can run.

### Automatic historical artifacts

After report publication, `make test` refreshes plots for the computer that
executed the run, on every architecture. Reports carry `host_identity` with a
domain-separated SHA-256 of `/etc/machine-id` and the running architecture;
raw machine IDs and hostnames are never published. Only committed reports with
that exact identity, overall PASS and all five stages PASS enter its history.
Git report history preserves each computer's measurements even though the
shared `test_results.json` is overwritten by the latest upload. The plotter
scans report revisions, never assumes the current file belongs to this host.
Outputs are isolated under `build/history/<architecture>-<full-host-digest>/`.
A missing/invalid identity fails closed. Legacy reports without identity remain
in their existing manually selected histories; ISA/CPU count cannot migrate them
automatically. After the exact-computer refresh, the ARM64 host also refreshes
its pre-existing NEON/seven-CPU legacy-cohort history separately under
`build/history/arm64-neon/`. The audited AVX-512 host additionally refreshes
the explicit `docs/handoff/x86-host-history.json` allowlist under its own
profile directory when its exact host digest matches. Neither reference chart
adds unauthenticated reports to the exact-computer history; the four-CPU SSE2
host receives no unverified automatic legacy selector. Reference refresh
failure is reported separately and cannot alter qualification. OS reinstalls start a new history, and cloned installations must
have unique machine IDs. Python Matplotlib must be installed for rendering.
It prints the latest plotted source and the local index path. Failed/blocked,
uncommitted and other-host runs never become this computer’s performance points. Plot
failure prints `NOT UPDATED` and diagnostics separately from the qualification
verdict; it cannot turn a failed device gate into a pass or hide a passed gate.
The stable index links to image/data snapshots keyed by report, plotter source
and collected data, so later refreshes cannot change an already shared plot
and corrected rendering/data can receive a fresh path. Retain the stable
latest files for local consumers, and preserve each snapshot once created.
Keep the absolute raw/swapz useful-WRITE MB/s chart alongside relative gains so
a changing raw control cannot masquerade as a product speed change. Previously
rendered chat images are snapshots; refreshed files live under the stable index.

For work moved to x86, the private history helper accepts an explicit audited
host JSON with full report SHAs and host identity digest. The receiving host's
profile is `docs/handoff/x86-host-history.json`; output stays under its distinct
`build/history/x86-*` directory. Selection also requires all five stages PASS,
eight-CPU identity for this profile and scalar/SSE2/AVX2/AVX-512 execution evidence.
Rootless report tests reject unlisted, incomplete, missing-CPU and wrong-ISA reports,
unsafe output names and missing host digests, while retaining ARM selector and
snapshot/line-break coverage. Verify legacy host/protocol before adding its SHA;
backend names and CPU count alone do not establish the same physical machine.
Show every newly generated/refreshed
plot inline. Keep configured emulation rates and achieved raw controls visible;
host-limited RAM emulation is synthetic software evidence, not a physical
Gen4/Gen5 device measurement. Do not change model settings to improve one arm.

### RAW READ slot qualification

Execute the target's actual RAW selection, slot preparation/decode and lower
completion bodies with the real authority CRC verifier. Reject corrupt/stale
RAW bytes and invalid geometry, preserve the independence/fence gate, and prove
RAW completion cannot seed the SWZ cache. Source checks keep cache prime/absorb
compressed-only and callback ownership unchanged.

The official loaded phase must additionally run byte-exact all-RAW and
half-RAW/half-compressed QD32 mixed traces on newly owned RAM-backed null_blk,
verify both complete images, and observe successful asynchronous READ batches
and lower READ requests. Its mandatory marker is correctness evidence separate
from the unchanged medium performance matrix; omitting it cannot qualify a run.

### Compression input telemetry

`direct_lz4_input_pages` counts ordered page-codec calls receiving the mapped
BIO input; forced RAW bypasses do not count. It does not count preparation
snapshots. `mapped_snapshot_input_pages` counts background/submitter inputs
whose single-BIO shape permits a mapped copy into the immutable RAW snapshot.
Both preparation paths compress that snapshot, after unmapping the source.
The latter counter is not zero-copy evidence. Old reports through `df861f74`
combined both categories under the direct-LZ4 label; do not infer copy savings
from that historical field. Independent WRITE-copy bytes and wall retain their
original scope. Real loaded development validation must observe mapped
snapshots for submitter-prepared ordinary input and preserve the byte oracle.



### Independent-target stripe development experiment

The `*-stripes` `make fast_test` scenarios are the development-only test for a
possible single-lower-WRITE-lane ceiling. They do **not** alter production C and
never enter `test_results.json` or qualification history.

One persistent mixed QD32 trace is generated with both WRITE and immutable READ
pages owned by a lane. For N=1,2,4, the harness partitions that exact trace by
`logical_page % N`. It renumbers only each target's local page/lane/sequence;
the fixture payload selected by every original operation is preserved. A
stride/offset prefill map preserves the original initial bytes after local-page
renumbering, and every child plan passes the ordinary complete-image oracle.

Each arm owns N separate RAM-backed `null_blk` devices. The swapz arm creates N
independent ordinary K=1 targets, one per lower. The raw arm uses N equally
modeled lower devices with the same page-to-stripe mapping. Aggregate offered QD
stays 32. Per-device bandwidth is the model bandwidth divided by N; per-device
hardware queue capacity is divided by N while preserving the model's submission
queue count, so aggregate modeled bandwidth and queue capacity do not grow with
N. NVMe5 is the primary model and SATA is a secondary control.

All N native replays finish warmup before a private start gate is released.
Aggregate useful throughput uses the earliest measured start and latest measured
end, not a sum of per-process MB/s. An observational sampler reads only the exact
owned lower devices and records maximum simultaneous WRITE-active devices and
aggregate WRITE depth. Its finite sampling interval can miss short overlap:
observing `>=2` swapz lower devices proves concurrent lower service; observing
less is inconclusive.

`STRIPE_COUNTS=` may select a unique subset of `1,2,4`;
`STRIPE_REPEAT=` defaults to five. Count order rotates by round and raw/swapz
arm order alternates. The existing quiet-host/raw-drift screens still apply.
Results stay in `build/tests/fast-test/latest.json` under
`striped_target_experiment`. Do not infer K=2 benefit merely from target-count
scaling: a reopen requires a material improvement in normalized swapz/raw
useful WRITE service, preserved lower-byte savings, and observed simultaneous
swapz lower WRITEs for N>1.
