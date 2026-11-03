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

### Primary lifecycle transaction-state contract

Primary lifecycle qualification must keep durable transaction state consistent
with independently observed kernel state. Durable `ACTIVE` requires proof that
the exact transaction-owned mapper is active in the Linux swap inventory.
After mapper creation and Linux swap-header initialization, the native
coordinator must pin the manifest-bound mapper block device, revalidate its
Device Mapper UUID/table/backing identity, prove both the raw backing partition
and mapper inactive in `/proc/swaps`, invoke ordinary `swapon` through that
descriptor's `/proc/self/fd/<n>` reference, and independently prove the exact
mapper active before persisting `ACTIVE`. A definite `swapon` error fails the
transaction even if later state is surprising; only an interrupted syscall may
be reconciled by exact active inventory proof.

Normal stop and recovery must use ordinary `swapoff`. If the exact
manifest-bound mapper is active, the coordinator pins and revalidates it,
invokes `swapoff` through the descriptor reference, then independently proves
the mapper and raw backing inactive before Device Mapper removal. A mapper
already proved inactive or absent requires no duplicate `swapoff`. A definite
`swapoff` failure must never permit mapper removal; only an interrupted syscall
may be reconciled by exact inactive inventory proof. Ambiguous inventory,
wrong-device activation, stale identity, or an active raw backing partition
remains recoverable and fail-closed. A stale run ID must never activate,
deactivate, remove, or complete a newer transaction.

`tests/runtime/native/primary-lifecycle-audit-test.py` is a rootless
adversarial model for those invariants and performs no privileged or physical
device operations. Its fake swap inventory must agree with the model's current
mapper state; only explicit inventory errors or wrong-device observations may
be injected. Source checks strip comments and quoted diagnostics before
verifying real syscall expressions and ordering, with a negative control that
rejects comment-only mentions. These checks guard against enabling the
privileged primary path without native swap operations, but the execution gate
remaining disabled is a safety block, not lifecycle qualification. Synthetic
model PASS does not establish current-host or production-C lifecycle correctness;
bounded real anonymous-page swap-out/swap-in evidence remains required.

### Primary real-swap native-host qualification

`docs/production-acceptance.json` is the canonical frozen quantitative
production-acceptance manifest. The real-swap helper and dedicated-SD
performance evaluator must consume that same file; duplicated mutable
threshold tables are not authoritative. A physical run must BLOCK if the
manifest is absent, malformed, not `FROZEN`, or if any requested cycles,
workload size, resident limit, swap limit or timeout differs from its
`primary_real_swap` values. The manifest also carries the exact prospective
physical workload/acceptance contract used by `qualification.py`, so a
threshold change is an explicit source-controlled policy change rather than a
runtime override.

`tests/tools/qualify-primary-real-swap.py` is private Agent-8 test
infrastructure, not a second public command; Agent 12 owns registration in
`tests/tools/test-rootless.sh` and the official test pipeline. It must BLOCK in GitHub-hosted CI and must never call
`swapon`, `swapoff`, Device Mapper removal, forced module removal, or create
fallback swap itself. Activation, deactivation, and recovery are requested only
through the production primary coordinator.

Before physical activation it must prove: exact clean source on `main` with
local `HEAD == origin/main == validated source` and a freshly queried remote
`refs/heads/main` equal to that source (unreachable or stale remote is BLOCKED);
current qualification
provenance; a frozen production acceptance manifest; the protected PARTUUID
selector; exact partition size and device number; the exact removable USB
parent and its sole selected partition; explicit
`root_same_physical_disk_as_target=false` and
`recovery_same_physical_disk_as_target=false`; no unresolved primary
transaction, mapper, module, or raw swap alias resolving to either the selected
partition or its physical parent disk; any unresolvable active block-swap
identity is BLOCKED; at least 1 GiB `MemAvailable`; readable kernel diagnostics; and working cgroup-v2 memory,
swap, PSI, OOM, and zswap controls. A missing storage-separation fact is
BLOCKED, not equivalent to false.

The helper must treat the installed `<prefix>/sbin/swapzctl` as the qualified
artifact identity, derive the same
`<prefix>/libexec/swapz/{dm-swapz.ko,device-roundtrip}` paths used by the
manager, parse the supplied owner report's qualified artifact hashes, and
independently SHA-256 all three installed files. It must not rebuild, replace,
or execute that installed production control for destructive qualification.
After exact clean-source admission, the helper instead compiles a root-owned
0700 temporary coordinator from the same current userspace sources with
`SWAPZ_PRIMARY_PHYSICAL_QUALIFICATION_TEST=1`, embeds the exact validated
source/clean provenance, and binds
`SWAPZ_PRIMARY_PHYSICAL_QUALIFIED_CONTROL` to the installed qualified
`<prefix>/sbin/swapzctl`. Only subprocesses invoking that private coordinator
receive `SWAPZ_PRIMARY_PHYSICAL_QUALIFICATION=1`; the parent environment and
ordinary installed binary remain disabled. The temporary coordinator must be
removed on every admitted disposition and its SHA-256 recorded in persistent
evidence.

The report values, private primary plan qualified/live values, embedded control
source SHA, and observed installed bytes must all agree with the exact validated
source. The plan's `privileged_execution_enabled=true` proves only that the
private physical seam and runtime marker are active; it never authorizes the
ordinary production binary. The module is deliberately absent before start, so
live module sysfs provenance is expected to be unavailable at admission and
must not be required there. Immediately after successful start, the helper must
independently require the loaded module's `build_source_sha`, clean bit, and
physical-backing parameter to match the validated source and production
physical mode. Trusting the plan's aggregate artifact-match boolean alone is
insufficient.

A disposable cgroup preflight must complete before primary `prepare/start`.
Default bounds are 384 MiB deterministic anonymous memory,
`memory.max=128 MiB`, `memory.swap.max=384 MiB`, cgroup zswap disabled,
128 MiB minimum real-swap evidence, two cycles, and 240-second finite waits.

Each live mapper cycle must use two concurrent deterministic oracle processes
and two complete allocate/swap-out/swap-in/byte-verify/release rounds. Every
worker's readiness, fill, and verification page/byte counts must match its
assigned memory, with worker PID/seed identity and fill-to-verification digest
continuity; aggregate totals cannot compensate for an incomplete worker.
The first round must return both dedicated-cgroup swap charge and exact mapper Used KiB to
the fresh zero-use baseline before the second allocation; only then is repeated
swap-slot reuse proven. While a round is resident under pressure, exact mapper
Used bytes must equal the dedicated cgroup's swap charge. Any difference is
BLOCKED because traffic attribution or mapper ownership is ambiguous.

Once recovery-storage admission is proven and before `prepare`, the helper
must durably create a root-owned 0600 attempt record under the validated
recovery base with a fail-closed
`FAIL/qualification_interrupted_or_incomplete` sentinel. The helper updates
that record before a cycle mutates state and after the cycle returns to durable
COMPLETE, then atomically fsyncs and read-verifies terminal PASS/FAIL/BLOCKED.
A crash or kill therefore leaves persistent non-PASS evidence without adding
evidence-I/O failure points inside the live lifecycle. Pre-admission BLOCKED
outcomes must not write to unverified recovery storage; Agent 10's official
runner integration must persist those runner-level dispositions.

A `PRIMARY_START=ACTIVE` message is insufficient. The helper independently
proves the run-bound mapper name/DM UUID/device number, exact one-line `swapz`
table and backing dependency, sysfs identity, valid Linux swap header with a
fresh nonzero UUID, raw backing absent from `/proc/swaps`, exact mapper
present with zero initial use, unchanged unrelated swap identity, and unique
highest swap priority for attributable cgroup traffic. Ambiguous attribution
is BLOCKED.

PASS requires actual reclaim and swap-in: at least 128 MiB cgroup swap
occupancy, at least the same 128 MiB increase in exact-mapper `/proc/swaps`
usage and swapz logical WRITE/READ counters, positive swapz physical WRITE and
READ counters using the production `failed=` and signed `error=` status fields, backing-partition WRITE and READ sector deltas whose 512-byte sector totals
cover the corresponding swapz physical-byte deltas (merely positive unrelated
device I/O is insufficient), positive `pswpout` and `pswpin`, zero OOM
events, healthy target status, and
byte-exact verification of exactly the admitted deterministic 4 KiB page
count and byte count; a truncated oracle report cannot qualify. PSI and
relevant kernel errors are recorded. Current-host evidence is mandatory; historical
reports or successful `swapon` without traffic cannot qualify.

Normal teardown is requested only through `swapzctl primary stop`. An
independent sampler must witness active mapper swap, then mapper-present but
swap-inactive, then mapper absence in chronological order; out-of-order or
regressing stable observations cannot qualify even if all states appear.
Disappearance while still in the known swap inventory is FAIL. A definite stop/`swapoff` failure is FAIL and cannot
be masked by sampling uncertainty. If correct teardown is too fast to prove
the inactive-before-remove interval independently, the result is BLOCKED, not
PASS. No force cleanup is allowed, including error paths. Oracle-child
termination may use bounded TERM/KILL for the dedicated test processes only;
signal-delivery exit races must not mask the underlying qualification failure,
and one worker's cleanup must not wait for the other worker to leave the shared
cgroup. Removal of the dedicated cgroup still requires every worker exited.

At least two passing cycles require new run IDs and Linux swap UUIDs, zero
initial mapper usage, no stale mapper/module/ownership state, durable
`COMPLETE`, and restored baseline swap inventory after each cycle. This
proves the non-reboot fresh-volatile-mapping property; cold-boot observation is
separate. `tests/runtime/native/primary-real-swap-test.py` provides rootless
parser, identity/provenance, traffic, byte-oracle, stop-order, disposition, and
cleanup mutants. `tests/tools/primary-real-swap-oracle.py` only allocates and
verifies memory; it configures no swap or mapper state. Agent 12 owns shared
runner/official-pipeline registration; Agent 8 must not edit that wiring.

### Development decision loop

The project-goal CI policy validates all five root Make targets
(`all install uninstall test fast_test`). This does not make `fast_test` a
second public qualification command: `make test` remains the sole official
qualification entrypoint.

`make fast_test` is the owner-approved development loop, not a qualification
command. It builds the current working tree (dirty trees allowed), runs the
native and replay contract checks (including the lower-I/O window policy and
offline page analyzer), runs the root preflight, and then runs
one counterbalance-free raw/swapz pair per selected scenario through the same
private owned null_blk pair helper and exact device models used by `make test`
(default: three repeats each of SATA mixed, NVMe Gen4 mixed, fast mixed,
fast QD4 and fast QD8). A selected `nvme5-stripes` or `sata-stripes` scenario runs the
existing mixed-QD32 multi-target N=1/2/4 experiment. `fast-stripes-w4` and
`fast-stripes-w8` run the same independent-target experiment with sustained
WRITE-only QD4 or QD8, respectively, as described below. It prints one table of useful READ/WRITE, lower WRITE bytes ratio
and requests, READ/WRITE p99, windows, deadline and idle-bound closes,
accepted-work lower idle, lower-WRITE service and its EWMA, and keeps detailed
telemetry in `build/tests/fast-test/latest.json`. `SCENARIOS=` and `REPEAT=`
select scenarios and repeats. Every emulated scenario must use the production
delta64 + `DELTA64_SHUF8` byte-plane shuffle (byte shuffle) + LZ4
stack. Delta64-off benchmark arms are retired and must not be added to
`make test`, `make fast_test`, report plots, or performance history.
Retiring the comparison does not retire positive-path correctness: the loaded
default-policy smoke writes and byte-exactly reads back 128 delta64-positive
counter-sequence pages (`--delta64-write-series`/`--delta64-verify-series`) and
requires at least 128 classifier passes and adoptions, proving encode, store and
DELTA64_SHUF8 decode on the loaded kernel's selected backend. The owner script
emits `PASS_LOADED_DELTA64_POSITIVE=pages:128 classifier_pass:N adopted:N`, and
the report parser requires and persists those counts in `loaded_correctness`
(a missing or short marker is INCOMPLETE). History plots
keep only rescue-on mixed points; retired write-only delta64-positive envelope
rows (no READ service) are excluded from mixed panels. A DM-linear calibration
file reports `compression_policy=none-dm-linear`.
`SUBMITTER_PREPARE=0` disables only the existing submitter-context path in
ordinary asynchronous development pairs (background async preparation stays on);
the product/default and official qualification remain `1`. The private helper
passes the read-only module parameter and verifies its effective DM status,
rejecting this opt-in for synchronous, linear and ID36 pressure controls.
`HOST_LOAD_PROFILE=browser-video-144p` (or `quiet-intended`) annotates the
development report only; it does not relax the pre/post CPU-PSI screens, raw
drift exclusion, or allow a busy run to be promoted. Compare like-labeled
host-load cohorts; no tag establishes an idle host. `HAND_RECORDS=8|16|64`
selects an early async work-conserving hand threshold for ordinary owned-null_blk
development pairs. Eight is the unchanged default; 16/64 are rejected for
calibration, stripes and physical backing. It never writes or publishes `test_results.json`,
never records a qualification verdict and never substitutes for `make test`:
single unpaired observations decide only which candidate deserves the full
owner matrix.

`CONTENT=medium` keeps the existing fixture. `CONTENT=entropy` supplies only
incompressible pages; `CONTENT=balanced` supplies equal numbers of medium and
entropy pages. These are synthetic content controls, not representative swap
populations. `CONTENT=representative` is an opt-in owner-supplied content cohort
for `make fast_test`; it requires `ANON_PAGE_SAMPLE` to name a local regular
file of 128..8192 concatenated 4 KiB pages. Invoke it as
`CONTENT=representative ANON_PAGE_SAMPLE=/private/path/pages.bin make fast_test`.
The sample is read without following
symlinks, copied with mode 0600 into the mode-0700 temporary plan directory,
and deleted with that directory after the run. The input's device, inode, size,
mtime and ctime must remain stable while it is copied. The owner supplies the
sample; neither the analyzer nor the benchmark reads process memory, `/proc`, a
swap partition, or any block device, and it never activates swap.

The native `anon-page-analyzer` consumes the temporary sample as a page stream.
It uses the production predictor, predictor-first direct-adoption path, later
packing route and 64-page extent planner. Its LZ4 settings match the production
defaults: acceleration 1 for ordinary pages and 4 for DELTA64_SHUF8 candidates.
It emits only aggregate size buckets, zero and exact same-filled counts, route
totals, selected predictor backends, LZ4 version and planner geometry. It
reports payload bytes saved and added so direct-adoption trade-offs remain
visible. It emits no page bytes, per-page records, page hashes or sample path.
Its working buffers are locked against swapping, dumpability is disabled, core
dumps are disabled, and sample buffers are explicitly cleared. The surrounding
Python plan/stripe process and every replay Python process must disable core
dumps and dumpability and use mlockall(MCL_CURRENT|MCL_FUTURE) before opening
representative pages. The fixture.json content profile reestablishes this
requirement across sudo; native replay must independently enforce it before
mmap and allocating workers. If memory locking is unavailable or RLIMIT_MEMLOCK
is insufficient, report BLOCKED rather than replay sensitive pages. Rootless
tests cover privacy-metadata detection and rejected lock setup. A rootless
fixture-plan test may SKIP its full replay on a runner without sufficient
RLIMIT_MEMLOCK only after observing the expected fail-closed protection error;
this is not an operator bypass or a passing representative replay. These protections
do not erase immutable Python copies before process exit; do not use highly
sensitive page corpora without separately reviewing that retention boundary.
Privileged ordinary and striped pair helpers snapshot the validated shared
fixture with `private_memory.py copy-fixture`, never generic cp/dd/cat. For
representative content the unprivileged fast-test orchestrator passes an
explicit `--private-fixture` classification across sudo. The helper still
checks metadata as a second signal, disables dumps and locks memory before
opening private bytes, rejects symlink/nonregular or changing sources, creates a
mode-0600 destination with exclusive creation, fsyncs it, removes only partial
snapshots it actually created on failure, and preserves any pre-existing path. This retains the root helper's immutable-input boundary
without exposing bytes to an unprotected copy process. The striped helper also
requires and copies the nonsensitive, nonsymlink `fixture.json` beside the
snapshot so each replay can reestablish privacy before reading page bytes.
Privacy metadata is opened once with O_NOFOLLOW/O_NONBLOCK and validated
on its file descriptor; a substituted symlink or FIFO is rejected without
following it or blocking. The protected snapshot source also opens nonblocking
to reject a substituted FIFO before its regular-file check.
Rootless tests must prove that a pre-existing snapshot path survives O_EXCL
failure after the privacy hook has run, without depending on the CI host's
actual RLIMIT_MEMLOCK; they must also prove that explicit private classification
forces the protection hook even when metadata says a synthetic profile, and
that both privileged helpers carry
that classification across sudo into protected snapshot/replay processes.
The paired `make fast_test` plan uses the same page file and immutable trace for
raw and swapz arms; its local ignored `latest.json` keeps the fixture digest for
pair identity and the aggregate analysis, but never the sample bytes or path.
This is representative-content emulation only: it does not qualify swap
semantics, source policy or physical-media behavior. A forced termination may
leave a private temporary plan under `build/tests/benchmark-plan.*`; remove it
before sharing build artifacts.

Each private pair loads the kernel LZ4 dependency before inserting
the product module, including the first development pair after a boot. Keep the selected content and the actual fixture metadata (weights,
page counts, measured LZ4 sizes and hash) in the development JSON, alongside the
immutable plan hashes consumed by both arms. A private helper's medium protocol
selects queue geometry; the shared fixture remains the content authority. Never
attribute a content change to a source optimization or mix these controls into
the qualified medium history. Representative-content results remain separate
from synthetic `medium`, `entropy` and `balanced` controls and from qualification
history.
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

Select observer gates from the actual replay-engine field: persistent lane
ownership alone does not imply native C replay or its stdin GO protocol.
Smoke-check the selected probe with the installed kernel/tool combination.
An attached observer with no timed gates is invalid. Explicit event loss or
missing independent syscall/lower counts rejects interval attribution; never
infer a complete critical path from the surviving subset. Preserve failed
captures and technical corrections separately from performance observations.

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

A fresh four-record-window mapping injects lower WRITE fault 65,535 within
at most 16 fixed series. Live handoff activity is proved on the preceding
suspend/drain mapping; fault-mapping handoff counts are diagnostic only.
Parallel writes must fail, the target must become terminal with one injection,
and completion ownership must drain. A fresh aligned direct WRITE must then
return exactly -1/EIO and increment the error counter without a new success.
The mandatory loaded marker binds these checks; missing, zero-activity,
wrong-volume, still-active or missing-failure evidence blocks qualification.
Actual target-body native tests cover busy-slot fallback, 4..64 bounds, close
between eligibility and lock acquisition, reuse while an old work call returns,
and failure before/during BIO delivery. Those tests must compile the production
completion and dispatch constants alongside the actual function bodies, rather
than supply a private four-record dispatch constant that can hide threshold
coupling. Four published BIOs must qualify while three remain inline, even
though the production early-dispatch hand is eight records.
Shell fixture assertions must include the window/ordinal/pass assignments
before the fault mapping UUID; extracting only the text after that UUID drops
the setup and fails qualification without exercising the intended contract.
Kernel queue scheduling and reclamation
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

Package install, upgrade and uninstall must preserve primary recovery authority.
An exact already-installed identity may return as a no-op, but any package
mutation is BLOCKED while `primary-state.json` or a partition ownership marker
exists. This prevents a package transaction from replacing the qualified
control/module snapshots needed to reconcile an interrupted primary lifecycle.
The rootless package suite must exercise both durable-state and ownership-marker
refusals and prove the installed bytes remain unchanged.

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

Native tests compile the real `src/kernel/{codec,authority,engine}.c` where applicable. They cover codec integrity, authority publication, torn/short failure, overwrite generations, discard, zero-write representation, online packing, randomized authority, lower-run aggregation, flush/FUA accounting, retention/window policy and GC rotation/cost invariants. The preparation codec-result regression executes the production `preparation-slots.h` classifier/publication helper and distinguishes negative errno to ERROR, zero to READY_RAW, and positive length to READY_COMPRESSED; zero/positive outcomes must also be exercised through actual state publication. It must exercise both deterministic publication interleavings, including ERROR winning before RAW selection and RAW_SELECTED winning before a late negative result; the latter proves the target caller still owns fail-closed handling rather than mutating the selected state. It must additionally race one producer and one RAW selector for thousands of iterations and require any observed READY/ERROR state to expose the producer's payload/error side data through the acquire publication edge. The exact engine tests must inject both a successful short lower WRITE and a lower WRITE that physically completes a nonzero prefix before returning `-EIO`; neither may publish a new mapping, trigger verify-after-write readback, or discard a previous authoritative generation. The native fault fixture must verify the acknowledged lower-media prefix against the encoded bytes and the unwritten suffix against zero-filled media; a fabricated partial completion without actual bytes is insufficient. The experimental exact-production-C GitHub workflow must execute the complete native suite with AddressSanitizer plus UndefinedBehaviorSanitizer on both x86_64 and arm64; do not duplicate that expensive pass in the project-goal workflow. On x86_64 it must then clean the native build and rerun the pthread preparation publication/slot-reuse probes with ThreadSanitizer, halting on the first race report. Native ASan/UBSan/TSan coverage is supporting evidence only and must not be reported as KASAN, KCSAN, lockdep or loaded-kernel race qualification. GC engine coverage must also force a fully completed batched lower write whose authority replay fails after at least one earlier extent has published; the wrapper must return the exact committed prefix while leaving the unpublished tail unreachable, so callers never retry already-authoritative pages as though the prefix were zero. A delayed GC lower completion must keep both overwrite staging and DISCARD fenced until replay, and failed GC lower I/O must leave the uncertain physical reservation unavailable for immediate reuse. A combined lower WRITE that reports a short physical prefix and -EIO must publish none of its staged extents, leave previous mappings byte-exact, quarantine all reserved blocks (including unwritten tail blocks), and retry from a fresh range.

The GC native suite must additionally sustain at least 64 all-RAW exhaustion-and-
rotation cycles over a fully populated logical mapper, verifying all surviving
pages byte-for-byte and preserving both rotating reserve roles after every
cycle; a successful mapper construction or two rotations are insufficient.
Every successful reserve rotation must permit at least one subsequent foreground
overwrite before the next `-ENOSPC`; at worst-case RAW occupancy the next
exhaustion must occur within one 256-block segment of successful foreground
writes. This operation-count bound is a deterministic forward-progress proof,
not a substitute for the frozen physical ten-second no-progress acceptance.
The test must distribute foreground rewrites across distinct physical source
segments and relocate at least 128 4KiB RAW survivors per successful rotation
on average; a sequence that leaves one survivor per victim is not sufficient.
It must also reproduce repeated *partial* GC failures after at least one
relocation has published. The serialized worker must retain and authenticate the
same victim/destination rotation, preserve the monotonic destination cursor
across failed READ/WRITE, short or uncertain lower WRITE, and interrupted
authority publication, then resume only still-authoritative victim members
after the fault is removed. Repeated recovery must verify byte-exact contents
and generations, must not consume a second reserve merely because the first
attempt failed, and must prove the evacuated source becomes reusable only after
its mapping and physical liveness reach zero. If accumulated uncertain
reservations exhaust the owned destination, qualification forbids cursor
rollback, live-reserve reuse or an unbounded internal retry. When the original
victim has nevertheless reached zero mapping and physical liveness, one bounded
authenticated roll-forward may make the full destination the next victim and
reuse that independently verified-dead original victim as the next reserve
destination. The worker token must remain active and be rebound to that exact
role handoff before foreground mutation can resume. If the old victim is not
fully dead, the operation must remain fail-closed. The exceptional worker
roll-forward path must independently verify every logical mapping and physical
liveness counter, not rely only on segment-mapping counts, before allowing a
recycle hook to touch the prior victim; contradictory metadata must be terminal. The exact-production DM GC
error boundary must still reject an integrity/authority failure (-EBADMSG or
-EUCLEAN) as terminal even with a live recovery token, while preserving
retryability for the known synchronous lower-I/O -EIO and per-write -ENOSPC.

The exact-authority regression must construct 255 distinct surviving RAW pages
in one victim, publish one relocation, abort one uncertain one-block lower
WRITE and relocate all remaining pages. The first destination must become full
and fail ordinary commit. Before a successful roll-forward, deliberately make
each independent deadness view disagree in turn: a valid map pointing into the
old victim, a nonzero cached mapped-page count with no such map, and a nonzero
physical liveness record. Every contradiction must return -EUCLEAN before the
recycle hook and leave roles, cursors and recovery ownership unchanged. A
recycle-hook failure must return its error with the same state atomicity.
After restoring consistency, roll-forward must evacuate that full intermediate
segment into the verified-dead original victim, preserve every byte/CRC and the
expected generation increments, leave the other reserve untouched, and permit
a subsequent foreground write. Native authority/engine tests remain supporting
evidence for this state transition; loaded worker qualification is still
required for production release.

Qualification must separately cover a non-full recovery tail: leave one block
in the current GC destination while the original victim remains live, then
require a two-block relocation to return -ENOSPC. Recovery must claim a
different independently dead reserve before promoting the blocked destination,
keep the original victim/forbidden-OPEN identity unchanged, rebind the worker
token to the replacement destination/probe/high-water, restart only the
remaining authoritative victim members, commit, and prove a subsequent
foreground write plus byte/CRC readback. Abandoned tail blocks must never
become authoritative mappings. The worker may perform at most one destination
role handoff per invocation; if no replacement reserve exists while foreground
mutation is fenced, the owned recovery is terminal rather than indefinitely
retryable foreground -ENOSPC. Status/rootless runtime-health coverage must
report serialized initial/current reserve-role counts and the successful
destination-advance counter, warn after the first role is consumed, fail at
zero or an impossible count, and degrade rather than assume health when those
fields are unavailable. Normal one-for-one GC/roll-forward must not decrement
the count.

The native authority suite must also exercise a fixed 16 GiB maximum-capacity
regression fixture: one SWZ header block,
1 MiB segment rounding, and the authority's `ceil(logical_pages / 8)` reserve
with its two-segment minimum. It must reject the first page beyond the maximum,
initialize the maximum, attach every capacity-dependent production authority
array, and calculate those array bytes from the compiled C types. The volatile
`struct swapz_map` must remain 16 bytes: raw mappings store their CRC32C in
the four-byte union, while compressed mappings store a zero-extended payload
offset in that same union; encoding-specific readers must not inspect the
other interpretation. The transaction sequence is retained separately with
one byte per physical block for a compressed extent's offset from its segment's
first compressed sequence, plus one 32-bit sequence base per segment. The
native test must cover the maximum 255 offset and fail closed on overflow. For the current
16 GiB fixture geometry this is 4,194,048 usable physical blocks, 3,727,616
logical pages (15,268,315,136 mapper bytes), 465,952 GC-reserve blocks, one
separate 256-block foreground COW segment, 15,268,311,040 Linux-usable swap
bytes, and 106,828,764 bytes (101.88 MiB) of capacity-index arrays. Compared
with the 20-byte map and no sequence index, the net compiled-array reduction is
10,650,884 bytes (10.16 MiB). The array figure excludes the target structure,
fixed scratch/cache/workspace allocations and allocator overhead; it is not a
total module-RAM measurement. Native
authority success does not prove that the loaded Device Mapper target can
allocate or operate at that size. The loaded 16 GiB fixture qualification must
create the matching maximum logical target over a separately owned 16,383 MiB
RAM-backed `null_blk` lower, then verify the exact DM UUID, table, mapper size
and lower identity. Device discovery may issue logical reads after the mapper is
published, so record the observed
mapper READ bytes without attributing them to a particular process. Require zero
logical writes, zero lower physical read/write counters, unchanged lower
statistics at construction, then use the opened-UUID-checked oracle to write and
read only logical page 0 and the final logical page byte-for-byte. Record the
resulting target and lower READ/WRITE bytes and require them to agree. This two
page boundary check proves indexing at the advertised size; it does not fill the
volume or qualify maximum-size occupancy, RAW-heavy sustained writes, allocation
churn or GC. Require the target's failed-I/O counter to remain zero. Until loaded
worst-case RAW/GC tests pass, report the value as a
source-derived authority admission limit and keep maximum-capacity operation
unqualified. Report-parser and Make-interface fixtures must synthesize this
same 3,727,616-page / 15,268,315,136-byte boundary; the retired pre-headroom
3,727,872-page marker is invalid evidence and must not be accepted as current.
The primary manager must consume the shared authority capacity-window helper,
and its rootless policy test must prove the helper's exact GC-reserve result for
both the 16 GiB fixture and current-card geometry. The same test must distinguish
raw backing swap size from Linux-usable mapper swap size: for the current-card
geometry the latter is 108,320,764 KiB, derived from 27,080,192 logical pages
minus the one mapper swap-header page. The read-only plan must emit that logical
value and the shared-helper reserve count; reporting raw partition capacity as
`linux_swap_kib` is invalid evidence. Incremental-build coverage must also
prove that changing `authority.h` rebuilds `swapzctl`; a stale manager
compiled against an older capacity policy is not qualifying evidence.

The direct authority suite must also run an allocation-free preflight for the
currently selected-card geometry recorded in AGENT_CONTEXT.md; this is a
source-level sizing oracle, not a host allocation attempt. For the current
124,787,884,032-byte partition, reserving physical block zero and rounding the
remainder down to 1MiB segments yields 30,465,536 physical data blocks and
119,006 segments. The maximum admitted logical capacity is 27,080,192 pages
(110,920,466,432 mapper bytes), with maximum logical index 27,080,191,
3,385,024 GC-reserve blocks, and one separate 256-block foreground COW
segment. Linux can use 110,920,462,336 bytes after its mapper page-zero swap
header. The first page beyond that limit must fail allocation-free with
`-ENOSPC`. Capacity-index payload is 776,070,968 bytes (740.1189 MiB); on a
4KiB-page host, independently rounding each current array to an allocation-page
boundary is 776,114,176 bytes, 43,208 bytes of page rounding. The largest one
is the 433,283,072-byte mapping array. vmalloc
metadata, page tables, fixed target scratch/caches/workspaces and allocator
implementation overhead remain outside those figures and require loaded-host
measurement. The same preflight must exercise an aligned near-`u32` physical
geometry without allocating it, proving reserve arithmetic and one-past-limit
rejection do not truncate or wrap. On 32-bit builds, reject otherwise-admissible
geometries with -EOVERFLOW if map or physical-liveness array byte lengths exceed
size_t; the output reserve and caller-owned arrays remain untouched. The native
oracle distinguishes that rejection from arithmetic admission on 64-bit builds.
A rejected geometry leaves the output reserve untouched: the test must refresh
a successful preflight before using its reserve for foreground-headroom checks,
not accidentally compute from an earlier poison sentinel.

The authority policy now enforces worst-case RAW forward progress instead of
merely documenting it. Its reusable contract takes usable physical blocks
(after the SWZ header and 1MiB rounding), keeps the GC reserve at
`max(ceil(logical_pages / 8), 512)` blocks, and independently requires one
256-block foreground COW segment. A candidate is admissible only when
`logical_pages + 256 <= floor((physical_blocks - gc_reserve_blocks) / 256) *
256`. The capacity helper applies that same gate plus the build's `size_t`
array-addressability checks, then reports the maximum logical pages, mapper
bytes (`logical_pages * 4096`), and Linux-usable swap bytes
(`(logical_pages - 1) * 4096`). The rootless primary-manager policy test must
independently enforce the same boundary: 3,727,616 logical pages for the 16 GiB
fixture and 27,080,192 for the recorded 30,465,536-block card geometry, with
the next page and the former zero-headroom 27,080,448-page userspace limit
rejected. Userspace must also reject the first segment-rounded physical geometry
above `UINT32_MAX` and the build's `size_t` map/liveness addressability before
emitting a Device Mapper table; it must never truncate a wider device geometry
into the kernel's u32 authority indices. The target constructor must call the
allocation-free authority geometry validator before any capacity-sized
`kvcalloc`, with `swapz_authority_init()` retaining its post-allocation
defensive recheck. Misaligned backing is `-EINVAL`; a valid but
too-small or one-past-capacity geometry is `-ENOSPC`; an otherwise admissible
map/liveness byte count that cannot fit `size_t` is `-EOVERFLOW`, with all
failure outputs untouched. The GC reserve is never reduced to recover page
count.

The native mapping suite must bind acceptance to allocator behavior on exact
production authority C: derive the maximum for an eight-segment fixture, reject
the next page, fill every admitted logical page as RAW, perform the first COW
overwrite from the mandatory foreground headroom, then force repeated
high-live GC reserve rotations while checking every surviving byte, generation
and RAW CRC. The GC high-occupancy suite remains the longer 64-rotation stress
proof; together these establish that capacity acceptance corresponds to actual
allocator forward progress rather than mapper construction alone. The native
authority suite must also sweep segment-rounded physical geometries across the
minimum and proportional-reserve crossover, verifying exact maximum and
one-page-over admission without a second test-side capacity formula. At full
RAW occupancy, it must exercise the single-stale-block extreme: a 255-survivor
GC relocation leaving exactly one destination block, an overwrite consuming
that final block, and a subsequent one-survivor reserve rotation. Every
surviving byte, RAW CRC, generation, and reserve-role count is checked. This
is an allocator invariant test, not a loaded-host proof. Allocator
edge fixtures that are not themselves capacity tests must still use an
admissible geometry: under this policy three physical segments have no positive
logical capacity because the two GC-reserve segments plus one foreground COW
segment consume the entire device, so the smallest such fixture uses four. The focused legacy dead-segment recycler may conservatively
reserve one additional segment after successful four-segment initialization
when it intentionally needs exactly one foreground segment to exercise
immediate recycle, hook-failure, and live-map refusal semantics; this test-only
restriction must not bypass or weaken the production geometry validator.
Indexed dead-segment metadata fixtures use the same admissible four-segment
minimum. GC forbidden-victim fixtures also use at least four segments and must
keep a live mapping in every otherwise permitted GC destination before asserting
that only the paused foreground and still-live victim remain, so `-ENOSPC`
proves the guards rather than relying on a rejected three-segment geometry.

The `/8` reserve change updates the admitted-capacity policy, not the serialized
SWZ records or authorization-header layout. `SWAPZ_SUPERBLOCK_VERSION` remains
1; no on-media capacity capability or format-version field is added. A maximum
capacity claim must therefore identify the source that implements the reserve
policy. Do not bump the superblock version for this policy-only change.

Source contracts validate behavior that requires the Linux Device Mapper target itself, including BIO ownership, queue/drain ordering, null_blk-only admission, lower-I/O accounting and current report/build contracts. They must accept stronger release/acquire terminal-failure publication in place of an earlier unpaired READ_ONCE spelling, including by providing an acquire-load shim when compiling extracted production C bodies; literal spelling checks must not reject a stronger synchronized implementation. Source-string assertions are secondary to executable production-C coverage. Assertions over emitted calls must preserve argument identity and order without requiring punctuation after a final argument; when a status stream is split across bounded emissions, inspect the reconstructed format/argument stream or the specific call that owns the argument.

Execute the worker's actual batch-selection C block with rejected-probe
outputs of zero and a nonzero poison value: either fallback must charge one
ordinary BIO. Accepted coalescing/fan-out batches retain their actual counts,
the final one-BIO budget skips batch probes, and 64 ordinary completions must
exhaust the quantum exactly. The regression must fail on the old zero-charge
path; merely finding a decrement in source is insufficient.

### Userspace compression-ratio status

Rootless native qualification compiles the production `swapzctl.c` directly and
executes its compression-accounting parser. Cover mixed compressed/RAW/zero
traffic, exact GC subtraction, RAW-only and zero-only cases, nonzero
lower-bulk-padding ambiguity, failed targets, arithmetic overflow, missing
fields, and a cross-counter snapshot that must retry. Include a similarly named
field such as `physical_write_reqs` before `physical_write` so the test proves
exact token matching rather than prefix matching.

The status implementation must require two consecutive identical relevant
snapshots before printing a ratio. The compressed-only result is available only
when committed counters can partition compressed SWZ extent bytes exactly; an
ambiguous padding configuration reports unavailable. These rootless checks
validate userspace parsing/accounting and build compatibility, not live Device
Mapper semantics; the official acceptance command remains `make test`.

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

Native production-C CI runs AddressSanitizer plus UndefinedBehaviorSanitizer
with sanitizer recovery disabled and runtime halt-on-error controls; x86_64
also runs the dedicated ThreadSanitizer publication/slot-reuse probes with
halt-on-error. A sanitizer finding is therefore a hard CI failure, not a warning
followed by continued qualification. These user-space production-C sanitizer
probes do not claim kernel KASAN/KCSAN/lockdep coverage; any such debug-kernel
evidence must be reported separately and never inferred from this CI.

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

Before the ordinary loaded smoke target is admitted, qualification must reload
the exact module for each constructor failure stage and force deterministic
`-ENOMEM` after: backing ownership, dm-io client creation, authority/sidecar
initialization, core scratch allocation, per-read-slot scratch, the ordered
workqueue, preparation scratch, and the preparation workqueue. Every failed
`dmsetup create` must leave the mapper absent, the owned lower with zero holders,
the lower block-stat line byte-identical, and `rmmod dm_swapz` successful.
The exact marker
`PASS_LOADED_CONSTRUCTOR_FAILURE_CLEANUP=stages:8 lower_io_delta:0` is a
mandatory loaded-correctness input. The selector must remain default-off and
must be rejected on non-null_blk backing so this qualification seam can never
turn physical construction into a fault experiment.

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
all teardown failures into one generic diagnostic. The owned-null_blk primary
lifecycle helper's fixed `FAIL_PRIMARY_NULLBLK_LIFECYCLE:` and
`BLOCKED_PRIMARY_NULLBLK_LIFECYCLE:` markers are also actionable loaded-stage
diagnostics: the reporter must retain the marker plus a bounded sanitized reason,
while stripping paths, long IDs and arbitrary host-specific text. Live progress
may print only the fixed marker label, never its private detail. Failure-phase
attribution must recognize the primary lifecycle rehearsal, its fixed
`setup`/`prepare`/`start`/`stop` subphase markers, and its named
interruption phase before any later benchmark-fixture default can overwrite the
operator-visible failure location. The subphase markers carry no device identity,
run ID or path. A `BLOCKED_PRIMARY_NULLBLK_LIFECYCLE:` marker from the loaded
helper is a qualification BLOCKED outcome, not a code FAIL; the reporter must
preserve that distinction while retaining the same sanitized diagnostic rules.
When the coordinator itself emits the fixed
`BLOCKED: primary-swap <operation> failed: <strerror>` line before the helper's
generic lifecycle marker, the reporter must attach only the strictly allowlisted
operation and strerror-shaped tail. Path-, ID-, or arbitrary-text-shaped tails
remain excluded from published diagnostics. Each owned-null_blk lifecycle
rehearsal must allocate a fresh root-owned evidence directory bound to the same
random ownership token used for its null_blk config. Clean teardown may remove
only that exact token-bound directory after the holder/mount/swap identity
checks pass. Quarantined evidence from an earlier run is retained for
investigation but must not block a later independent rehearsal merely because a
fixed historical evidence path still exists. Loaded correctness qualification
must require the canonical primary lifecycle PASS record, the exact ordered six
initial start/stop fresh-process interruption PASS phases plus the five
fresh-process recovery interruption phases, the resulting eleven-case
interruption-recovery aggregate, and the separate thirteen-case negative-recovery
aggregate. Missing, duplicated (including repeated lifecycle or aggregate PASS
records), substituted or malformed lifecycle markers make Stage 5 evidence
incomplete; the parser must not silently overwrite an earlier PASS match.
Merely executing the helper or recognizing its failure markers is not sufficient
for a qualification PASS. The loaded report parser must require those same
eleven phases in canonical order and the `cases:11` interruption-recovery
aggregate; a legacy six-phase marker is incomplete evidence. The separate
negative-recovery aggregate must require all thirteen mandatory cases, including
definite pre-effect `EIO` failures for both `swapon` and `swapoff`, and
must carry `definite_io_error:true`. Those definite errors are never reconciled
as ambiguous success: start remains recoverable without activation, and stop
preserves the active mapper until a later independently successful normal
`swapoff` proves deactivation. The human qualification summary
must also display the verified process-death recovery count and negative-case
count so reviewers do not need to infer lifecycle coverage from raw log text.

Benchmark telemetry and storage-envelope parsers must safely handle directional workloads where specific operation latencies are omitted (for example, read p99 latency during write-only saturation or delta64 rescue sweeps), converting missing numeric fields safely without type errors.

### Direct-I/O and memory input qualification boundary (ID43)

Direct-I/O tests covering segmented and offset user buffers (via `transfer_segmented()` and `series_segmented()` with `pwritev`/`preadv`) qualify user buffer alignment, non-zero `bv_offset` translation, and multi-segment BIO boundary handling through the Linux block layer. In addition, explicit Transparent Huge Page (THP) compound folio backing (via `series_thp()` with `--thp-write-series` and `--thp-verify-series`) exercises incoming direct I/O from 2MiB compound memory regions. The fixture populates an aligned anonymous range, requests `MADV_HUGEPAGE`, then requires `MADV_COLLAPSE` to succeed before I/O; the hint alone does not prove that the kernel supplied a compound folio. Kernel-level passive inspection counters in `dm-target.c` observe:
- `bio_segments_gt1`: admitted BIOs spanning multiple bvec segments.
- `bio_segments_max`: maximum segment count observed on an admitted BIO.
- `bio_nonzero_offset`: admitted BIOs with non-zero within-page `bv_offset`.
- `bio_compound_folio_pages`: admitted BIOs whose backing memory is a compound folio (`PageCompound()` or `folio_test_large(page_folio())`).
- `bio_copy_fallback_pages`: write pages where direct LZ4 mapping was safely bypassed in favor of accounted copy fallback. This status field aggregates the ordered owner, background preparation producer, and ID150 submitter-preparation owners exactly once; changing execution placement must not hide fallback coverage.

Loaded qualification on owned RAM asserts `segs_gt1 > 0`, `segs_max >= 2`, `nonzero_off > 0`, `compound_pages >= 128`, and `copy_fallbacks > 0`, while preserving byte-exact verification across all segmented, THP, and cross-mode reads and writes with zero DM target failures.

The completion-handoff loaded fault gate must not rely on an early fixed lower-WRITE ordinal that can move ahead of the first handoff when preparation placement changes. The fixed 128-page × 129-round parallel series supplies 16,512 logical WRITEs with eight known zero elisions. The ordinary live suspend/drain probe keeps the product 64-record window and repeats that same series at most 16 times, polling each writer until it exits (no fixed poll budget), and suspends only after a handoff newer than that pass's baseline is seen while the writer is alive; completed WRITEs are counted for that pass only. The separate correctness-only fault mapping uses the minimum handoff-capable four-record window. That bounds each lower run to at most four records, guaranteeing at least ceil(16,504 / 4) = 4,126 lower WRITE attempts per series. With test_fail_write_nth=65,535 and at most 16 passes, the gate therefore guarantees 66,016 possible attempts while giving the same target up to fifteen complete passes to exercise a real handoff before terminal failure. Stop at the first non-success writer exit, which must be the injected failure. The fault gate still requires at least one real offloaded completion batch before terminal failure (handoffs are refused once the target has failed), exact fault-call/injection counts, drained completion ownership, upper EIO completions and the post-failure direct-WRITE EIO probe. Report every predicate (handoff count, active state, target failure, fault calls/injection, upper error completions, passes) on failure. This changes only qualification geometry/timing; production C, the product 64-record window, the fail-closed path and write-fault mechanism remain unchanged. BIO shape and compound folio inspection in `swapz_map()` strictly gates `bio_for_each_segment()` iteration to data-carrying operations (`REQ_OP_READ` and `REQ_OP_WRITE`) with positive sector counts, preventing invalid bvec traversal on non-data requests (e.g., `REQ_OP_DISCARD` or empty flushes). Failure context extraction in the test harness explicitly distinguishes each loaded subphase (`START_LOADED_COMPOUND_BIO`, `START_LOADED_LIVE_GC`, `START_LOADED_DISCARD_TRIM`, `START_LOADED_PACKED_PLACEMENT`).
Privileged qualification shell entrypoints under `tests/tools/` are executable repository artifacts; content-only Git-tree updates must preserve their existing executable mode so CI and the public Make contract exercise the same entrypoint the owner runs.

## Benchmark pairing and provenance

The mandatory mixed matrix uses two RAM-only latency models: 10 MiB/s with 1 ms completion and 80 MiB/s with 0.15 ms completion. The slow model remains a bounded four-session directional control (two sync, two async). The fast model runs ten sessions in the fixed sequence `0,1,1,0,0,1,1,0,0,1`, which forms five adjacent counterbalanced sync/async matched rounds. The control candidate inside every session is `off`; the product candidate is `swapz`.

Both arms of every session carry the same exact source SHA, fixture SHA-256 and trace SHA-256. Missing or divergent provenance is INCONCLUSIVE. Every logical workload must finish its byte-exact oracle before a performance verdict is considered. The five fast matched deltas use a two-sided Student-t 95% confidence interval with four degrees of freedom. Report both the paired mean and interval; do not replace paired analysis with an interval over unpaired arm means.

The write-only QD1/4/8/32 sweep is sustained offered-load evidence: workers are pre-created, warmup finishes before a common measured start gate, and each worker owns a disjoint ordered logical-page lane. No per-I/O Future submission or full-QD wave barrier is permitted in the timed path. Slow QDs and fast QD1 stay directional; fast QD4, QD8 and QD32 each use the ten-session confirmation sequence and paired 95% confidence intervals for logical write throughput, lower requests and lower bytes. This produces exactly 40 write-only sessions across both synthetic regimes. Historical wave-driver intervals are burst evidence only and cannot promote sustained-QD performance. Rootless Make-interface/source fixtures must assert the shared sequence, persistent replay mode and fast-QD4/QD8/QD32 mode selection.

The generated source-provenance header is shared by native userspace and
staged Kbuild sources. It must define the SHA, numeric clean state, and string
clean state from the same Make invocation. Stage 2's Make-interface regression
checks the generated string form required by kernel module metadata, including
the clean source fixture case.

### Dedicated SD performance and sustained-workload qualification

Physical performance qualification is separate from the mandatory owned-RAM
matrix and does not change the single supported \`make test\` interface. It is
scheduled only when the current protected target passes the physical identity,
source/artifact and lifecycle gates in \`AGENT_CONTEXT.md\`; no agent may start it
while another host task owns the card. The private implementation is
\`tests/runtime/benchmark/{sustained-replay.py,anonymous-swap.py,qualification.py,physical-campaign-evidence.py}\`.
The campaign-evidence helper is read-only with respect to devices and does not
schedule workloads; it snapshots and seals scheduler-produced evidence.
Rootless contracts for these helpers live in the already-executed
\`io-replay-test.py\`, so this addition does not create another official runner.

The prospective contract is source-controlled and immutable for a confirmation
campaign. `tests/runtime/benchmark/qualification.py` loads its exact
`physical_qualification` object from `docs/production-acceptance.json` and
must fail closed if that frozen manifest is missing or malformed. Rootless
contract tests resolve that manifest from the repository root, never from the
caller's current working directory. The frozen v1 contract defines four
workloads: five paired balanced-content service runs, five paired
representative-content service runs, one directional high-occupancy hour-long
pair, and three directional actual-anonymous-swap pairs. The separately frozen
prospective v2 amendment
\`tests/runtime/benchmark/physical-qualification-amendment-v2.json\` is bound to
the exact v1 manifest Git blob and adds two non-pooled five-pair cohorts:
physical QD1 balanced service under the existing service-v1 criteria, and QD8
entropy/incompressible service under its prospectively declared non-regression
criteria. Editing the v2 amendment in place is forbidden; the evaluator pins
its Git blob and any criteria change requires a new protocol version. A v2
campaign must invoke the evaluator explicitly with \`--protocol v2\` and includes
all six workloads. The service pairs use 20% READs, 10% occupancy, 65,536
warmup operations and 1,048,576 fixed measured operations; the v1 and
incompressible cohorts are QD8 while the dedicated QD1 cohort is QD1. Their
arm order is fixed before sampling as
raw-first, swapz-first, swapz-first, raw-first, raw-first. Each arm is externally
bounded to 1,800 seconds. The sustained pair is raw-first, maps the manager's
maximum logical capacity, fills 90% with proven entropy content, churns an 80%
hot region at QD16/20% READ for 60 seconds warmup plus 3,600 measured seconds.
The measured phase must report deterministic hot-page overwrite coverage, and
both raw and swapz must reach at least one second-cycle overwrite; GC activity
alone cannot substitute for repeated logical overwrites. The whole-arm timeout
is 14,400 seconds. The anonymous cohort order is
raw-first, swapz-first, raw-first; each arm uses an exact 1 GiB anonymous
working set under a 512 MiB cgroup memory.max, with memory.swap.max unlimited
or at least 512 MiB, performs three full verified read rounds, and is
externally bounded to 1,800 seconds.

Physical block replay must fail closed unless it is bare metal, root, clean
\`HEAD == origin/main == source_sha\`, and holds the private nonblocking host
benchmark lock. The protected \`/etc/swapz/primary-target\`, PARTUUID alias,
partition major:minor/bytes, removable parent major:minor/model/transport,
sole-partition topology and source-chain exclusions must all still match the
scheduler's pinned admission record. Fixtures, reports and root storage may not
reside on that parent disk. Raw replay requires no holder and starts at byte
4096 so it cannot overwrite the SWZ header. Swapz replay requires exactly the
expected fresh mapper holder/UUID/table and zero initial logical/physical WRITE,
GC-victim, window and failed counters. Block replay refuses any active swap or
mount identity; actual-swap qualification is performed only by the separate
bounded anonymous worker after the scheduler intentionally activates the one
admitted swap device.

Content classification is metadata-bound. Each fixture's SHA-256, page count
and 4096-byte page size must match its sidecar metadata. \`entropy\` requires all
pages to be entropy-profile RAW pages; \`balanced\` requires exactly equal medium
and entropy page counts; \`representative\` requires the private representative
classification. Representative fixtures retain the existing no-dump/mlock
protection and fail closed if it cannot be established. A filename never proves
a content class.

The sustained replay's write permutation has a closed-form inverse, so latest
page generations are reconstructed from per-lane completed-write counters. It
must never allocate a logical-page map proportional to the advertised swap
capacity. In-flight buffers, latency histograms and minute buckets remain
bounded by queue depth/run duration. Fill, warmup and measured work reuse one
bounded QD worker pool so cached pthread stacks cannot make memory scale with
phase count and worker creation stays outside the timed measured phase. The
final oracle streams every occupied page and compares the independently
regenerated expected bytes. The untouched
filled tail is read before that full sweep and is the cold-read phase. A
physical maximum-capacity run therefore proves high logical occupancy without
allocating the logical capacity in host RAM.

Every arm preserves a JSON result on success or failure. Pair records embed
both arms, exclusion state and every exclusion reason. SIGTERM/SIGINT delivered
to a physical benchmark worker must produce an explicit FAIL result when Python
receives the signal. Benchmark and campaign JSON publication must be atomic,
0600 and create-only: fsync the complete temporary inode before publishing its
final name, refuse an existing file or symlink without following it, and remove
the temporary inode on storage failure so partial JSON is never presented as a
result. A later attempt must not overwrite that existing result path. There is
no automatic retry. The evaluator counts every recorded attempt, including failed/excluded
attempts: a later PASS cannot replace an earlier attempt, pair IDs must be
unique within a workload, and every pair plus both embedded arms must share one
exact source SHA across the campaign. Mixed-source evidence is incomplete and
is never pooled. The 200 ms pre/post quiet windows reject busy >25%, CPU PSI \`some\` >5%,
steal >1%, unavailable required counters, or timed-arm steal >1%. A five-pair
service cohort is additionally unusable when raw useful-WRITE max/min spread
exceeds 10%. Exclusion never converts a failing correctness result into a pass;
it only prevents performance interpretation. Confirmation remains incomplete
unless every prospectively fixed pair survives screening.

Five-pair service claims use paired fractional deltas and a two-sided Student-t
95% confidence interval (df=4). PASS requires: useful-WRITE CI lower bound
>=+5%; normalized lower-WRITE-byte and lower-WRITE-request CI upper bounds
<=-10%; READ and WRITE p95/p99 CI upper bounds <=+25%; and measured
CPU-per-useful-byte CI upper bound <=+50%. Sustained percentile histograms use
16 sub-buckets per power-of-two range (<=6.25% relative bucket width). The
single sustained pair is explicitly directional and requires swapz/raw useful
WRITE >=1.05, normalized
lower WRITE bytes/requests <=0.90, READ/WRITE/cold p99 <=1.25, last/first
quartile throughput >=0.75, last/first quartile p99 <=1.25, GC wall <=20%, zero
GC no-headroom skips, positive victim relocation and segment programming, zero
target failure, zero byte mismatches, at least one measured hot-page rewrite
in both arms, <=10 seconds measured-interval maximum no-progress, <=128
MiB absolute post-exec replay-process peak RSS through measured completion and
<=1.25 GiB observed metadata+target peak RAM. On Linux this must come from the
bounded, strictly parsed `VmHWM` field in `/proc/self/status`, not
`getrusage().ru_maxrss`: resource high-water counters survive `execve()` and
can therefore charge the replay for memory previously used by its launcher.
The measurement-boundary VmHWM value and growth remain diagnostics only;
setup-time allocations within the replay process cannot be excluded from the
memory gate. Rootless contract coverage must parse canonical Linux VmHWM text,
reject missing, zero, wrong-unit and duplicate fields, and exercise the live
self-status reader so malformed accounting cannot silently qualify.

Anonymous-swap evidence is also directional: all three pairs must observe at
least 128 MiB of workload-specific process/cgroup swap and at least that usage
on the sole admitted swap device before each timed reread. Every timed reread
round must independently show positive \`pswpin\`, private-cgroup major faults,
exact-target READ bytes and backing-device READ bytes; the whole arm must show
positive \`pswpout\`, exact-target WRITE bytes and backing-device WRITE bytes.
The worker must remain the sole process in a private cgroup with no descendant
cgroups, and the admitted swap identity must remain unchanged. The first-byte
latency histogram still includes Python access overhead and resident accesses;
aggregate kernel/cgroup/I/O counters prove swap activity for the round, not
that each individual latency sample was a major fault. Every pair requires
byte-exact recovery, swapz/raw swap-in p95/p99 <=1.25, useful read >=0.80,
normalized lower WRITE bytes/requests <=0.90, and measured CPU/useful-byte
<=1.50. This is the only benchmark cohort that establishes actual anonymous
swap-in-sensitive reads; direct block replays and representative fixture
emulation must not be described as Linux swap behavior.

Independent lower-device accounting uses the selected card's parent block
statistics bracketed around each measured interval and separate cold-read
brackets. Peak target RAM is sampled every 100 ms from a one-second pre-create
baseline through mapper creation/workload plus two seconds of quiescence; record
\`MemAvailable\`, \`SUnreclaim\` and \`VmallocUsed\`, and use the baseline-median minus
minimum-\`MemAvailable\` delta as the conservative metadata+target peak. Repeat the
same host sampler for the raw control. This whole-host observation is deliberately
conservative and not exact allocation attribution, but an estimate from C type
sizes alone cannot satisfy the gate. Reports include useful throughput, p95/p99,
CPU, peak RAM, GC and allocator costs, lower bytes/requests, minute drift and
forward progress. Anonymous reports retain diagnostic process-CPU phase splits
for fill and reread/verification without changing the frozen whole-arm CPU
metric. Sustained interval telemetry reports observer wall time, sampler-thread
CPU and child-process CPU: sampler-thread CPU remains charged to the replay
process acceptance metric, child CPU is separate, and no observer cost is
subtracted post hoc.

The physical campaign evidence helper is mandatory executable qualification code; rootless benchmark coverage must import it directly before physical evidence can qualify.\n\nThe physical scheduler must take
\`physical-campaign-evidence.py snapshot\` records before the first arm and after
the last arm from the clean exact source and admitted partition. The snapshot
captures source tree, bare-metal status, kernel/node, CPU/affinity/frequency
policy, memory, PARTUUID/device/model/transport/queue/scheduler, block ancestry,
swap/mount inventories, PSI, thermal readings and swapz module parameters. Each
physical arm must independently record the module boundary after admission:
raw requires \`dm_swapz\` absent, while swapz requires loaded
\`build_source_sha\` equal to the exact arm source, \`build_source_clean=1\`, and
\`allow_physical_backing\` equal to \`1\` or \`Y\`. The evaluator excludes any
pair missing or violating that provenance, and the campaign sealer re-runs the
same evaluator before it can emit PASS. After
evaluation it must call \`physical-campaign-evidence.py seal\` with both snapshots,
the evaluator summary and every pair JSON. The create-only sealer hashes the
frozen policy, prospective amendment, evaluator and itself; verifies original
pair fields against the summary; preserves failed/excluded attempts; and only
emits campaign_status PASS for a complete v2 PASS with stable source, kernel,
device queue/scheduler, CPU policy/affinity, swap identity and module cleanup
state. A v1 numerical PASS is sealed as BLOCKED rather than promoted. Host
lower-WRITE reduction is not a direct NAND endurance/wear measurement and must
not be reported as one.


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

Source contracts show structure, not loaded semantics. Native C shows portable product logic, not Device Mapper runtime. W=1/W=2 shows compilation, not correctness. Owned RAM-backed loaded tests show real kernel BIO behavior on the test host, not physical-media benefit. Behavior on a particular real device requires physical evidence from that device. The current dedicated SD-card target already has standing owner authorization under AGENT_CONTEXT; no additional per-run reviewer/owner permission upgrades a lower evidence level into physical evidence.

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


### ID178 ACK-batch accounting validation

The actual completion loops must keep the batch record stack-local, sample one
delivery timestamp before the cohort, assign the record before each successful
BIO delivery, never dereference a BIO after `bio_endio()`, and aggregate all
per-BIO bins before releasing the completion slot. An executable actual-body
probe must validate immediate/deferred counts, duration sums, bin edges, the
shared-clock path without per-BIO clock reads, synchronous-window cohort
coverage, direct fallback and invalid timestamps; completion failure injection
remains covered by the ownership probe. A missing synchronous publication
observer mark must use the same cohort timestamp as a conservative zero-dwell
fallback, never a fresh per-BIO clock. Any actual-body completion-handoff
harness that extracts the production delivery loops must mirror every ACK-batch
field those bodies consume (currently the cohort `delivered_ns` mark), so a
structural telemetry change cannot fail only because the mock layout is stale.
The cohort timestamp intentionally replaces per-BIO delivery clocks, so absolute
ID178 ACK-dwell values may shift by at most the delivery-loop span and must not
be pooled as byte-for-byte-equivalent telemetry across this boundary.

### Lower-lane gap attribution: native and replay qualification (ID178)

The observational ID178 module compiles the pure `src/kernel/lane-gap.h`
helpers directly in `tests/runtime/native/io/lane-gap.c`; test every
timestamp-order permutation on the bounded grid, invalid/zero marks and the
successor/dwell bin transitions. Rootless source contracts forbid scheduling,
lock, wait, queue, or allocation calls inside the accounting helpers; require
the new per-BIO timestamp fields without changing ID114's marks, sole
ordered-domain chronology, generation-safe `profile_epoch` invalidation,
seal-start t3 (`commit_start_ns` before prepare; window start or previous
publication for synchronous runs), accounting only after the lower WRITE left,
inert engine hooks outside a foreground window (GC), exact synchronous per-run
sealed ranges, per-run synchronous post-publication observation, and sampling
publication-to-ACK before `bio_endio()`. An executable probe compiles the
actual chronology helpers (publish, submit, foreign note, both engine hooks,
window begin/end) and drives paired, successor-bin, published-prefix, foreign
before/after t0, generation-race, stale-finalizer, GC-hook, two-run
synchronous and unsubmitted-seal sequences; mutants that drop the GC guard,
skip predecessor invalidation on an unpaired submission, or compare foreign
writes against publication instead of t0 must fail it. The native lower-WRITE aggregation test must
exercise both synchronous observers in planned and batched paths, prove that
the sealed observer runs before lower I/O, and prove that authority is already
visible when the publication observer runs. Source contracts must also require
gap submission to scan only the exact run's planned-page range so an already-
published prefix cannot inflate successor availability. Existing rootless C probes that
extract full production function bodies must provide harmless ID178 helper
stubs or the new passive epoch flag in their local miniature test structures;
they must continue asserting their original completion, FIFO and quantum
semantics. Those probe stubs are not substitutes for the separate ID178
accounting source/native tests.

Timed `io-replay.py` K=1 WRITE counter deltas require every ID178 status
token: absence is an error, never zero. Replay/report validators require
`lane_gap_invalid == 0`, sum of the six phases equal to
`lane_gap_wall_ns`, and submission conservation across paired, foreign,
unpaired, and invalid outcomes. Both successor-count families must sum to
paired plus foreign gaps; for every threshold, the owned-tail count cannot
exceed the admitted-tail count. Deferred and immediate ACK dwell bins must
each sum to their count, deferred count must not exceed successful deferred
upper completions, and the total sampled count must not exceed successful
upper WRITE completions. Owner READ overlap may annotate paired and foreign
gaps but must not exceed their combined measured wall time. Empty paired or
foreign buckets cannot carry nonzero wall time. Counter deltas may not be
negative. The descriptive `benchmarks.lane_gap_attribution` rows and the
single console table **SSD lower-lane gap attribution** cover SATA, NVMe4,
NVMe5, and fast mixed. They report paired/foreign/unpaired coverage, foreign
wall time, all six phase shares, the full admitted and ordered-owned successor
histograms (0/1/2-3/4-7/8-15/16+), owner READ milliseconds/count at three-decimal-ms precision, deferred ACK
p99 as an inclusive histogram-bin bound, and host busy. The same table is
printed and retained by `make fast_test`; its default ID178 mixed set includes
SATA, NVMe4, NVMe5, and fast mixed. None of these fields decides a policy,
publication or qualification scorecard. `plot-history.py` ignores these
new properties until an owner-approved history design exists.

## Immediate K=1 critical-path profiling gate (ID114)

The profiling-only source keeps K=1, the existing four-record service rule, one
unbound preparation producer, the 64-slot reservoir, ordinary LZ4 acceleration
one and current SWZ geometry. `make fast_test` defaults to three repeats each
of SATA mixed, NVMe4 mixed, NVMe5 mixed, fast mixed, fast QD4 and fast QD8. The existing
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
wake-to-worker scheduling attribution. Ordered-worker scheduler-update runtime samples and phase wall clocks are
separate diagnostics. Their scopes may overlap, so they must not be summed into
a serialized or removable-CPU budget; they do not establish an exact split
among CPU, lower-I/O sleep and off-CPU wall time. After warmup and before the timed status snapshot, the replay harness sends
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
- **ID67 predictive rescue:** the production delta64 + `DELTA64_SHUF8` + LZ4
  stack is fixed on for every emulated device by owner decision. The second LZ4
  pass has a read-only `delta64_lz4_acceleration` control, default 4 (the
  qualified value; `PRODUCTION_DELTA64_LZ4_ACCELERATION` in the reporter).
  Routine rescue off/on A/Bs are retired; performance qualification must verify
  the production defaults rather than override them. RAW or >2024-byte LZ4 baselines use
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

Routine loaded qualification must not run a delta64 rescue off/on A/B. The
production stack is fixed on, and every emulated-device performance record must
report `delta64_rescue=1`, `delta64_lz4_acceleration=4`, and ordinary
`lz4_acceleration=1`. Preparation ownership may still be background-producer or
ID150 submitter context; the normal timed telemetry contract checks submitter
policy, ownership quiescence, claim/page conservation and complete WRITE-copy
attribution. Medium content may legitimately produce zero delta64 adoptions;
byte-exact transform/codec tests provide the positive functional coverage
without spending loaded benchmark sessions on a disabled performance arm.
Rootless reporter tests must reject any emulated performance record whose
production compression policy is disabled or mismatched. Synthetic loaded
transcripts used by rootless Make/report contracts must mirror the same
production-on storage-envelope markers and must not manufacture rescue-off
benchmark arms. Keep negative disabled-policy fixtures only where they prove
that such a performance record is rejected.
Do not claim this placement change itself improves service or endurance: the
five-pair timed outcome remains the performance decision.

Parallel READ service is separate: it requires private read scratch and must
dispatch immediately when lower I/O is idle. Reordering/coalescing is permitted
only for reads already waiting behind active lower work.

Genuine device-originated/partial lower errors, representative long-run
resource/churn pressure, larger controlled cold-read working sets, automatic
device-queue-depth policy, actual kernel swap, physical-device behavior and
physical endurance remain evidence gates. The current owner matrix already
satisfies the bounded ID36 deliberate CPU-oversubscription/low-RAM gate and the
promoted five-pair statistical protocols. On the dedicated SD-card host these
physical/actual-swap gates are active work under AGENT_CONTEXT rather than
blocked on another owner authorization.


### zswap collaboration qualification

See [context.md](context.md) for Linux swap and zswap code paths and the staged
[ROADMAP.md](ROADMAP.md) for planned origin and RAW-bypass experiments.
This is an actual-swap qualification gate. It does not change the generic
owned-RAM `null_blk` matrix, but the dedicated-host standing scope in
AGENT_CONTEXT authorizes the bounded `swapon`/`swapoff` work needed to close
it on the verified SD-card target.

Before origin-aware code can promote, source/native fixtures must prove
explicit origin propagation across simulated BIO split/clone, correct
unknown-origin fallback, producer-claim/snapshot/RAW atomicity, exact
one-owner completion, and no compressed result republished after RAW selection.
Tagged bypass must perform zero ordinary LZ4/delta64 attempts and produce
byte-exact readback through the existing CRC/generation and GC mapping rules.
Include duplicate-page ordering, overwrite, DISCARD, PREFLUSH/FUA,
suspend/drain, fault/uncertain lower completion, and preparation-slot cleanup.

During authorized actual-kernel-swap qualification on the dedicated host,
loaded tests must force and distinguish: zswap accepted with no backing write,
initial zswap
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

Any subsequent actual-swap correlation claims require safe dedicated-host
kernel-swap qualification under AGENT_CONTEXT, including a fixed kernel source,
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
module/device work. On that failure, the unprivileged parent prints the
repository-relative unstaged and staged tracked paths, excluding the report,
without touching privileged devices or disclosing host-specific Git metadata.
Report-only publication uses the same exclusion for both the tracked worktree
and staged index, including the concurrent-remote refresh gate. Genuine source
changes must never be ignored to obtain a qualification PASS.


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

If an ID36 owned pair has already failed (including an OFF/control replay
timeout), its shell exit path may release only its proven, private
`pressure.stop` barrier before ordinary positively identified device cleanup.
Successful pairs must keep the same pressure helper and burners alive through
all byte-exact verification and teardown; failure release never changes the
failed verdict, replay bounds, pressure admission or required evidence. Early
failures without a positively identified pair barrier leave stop ownership to
the enclosing ID36 helper. An outer timeout or uncertain live mapping still
quarantines rather than forcing removal; unattended cleanup must be separately
confirmed by loaded owner evidence.

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
directly against the compact per-extent sequence index. It must not copy all
4096 bytes into read scratch merely to decode one record. If the selected
payload overlaps block zero, copy only that exact payload fragment; CRC
validation must cover the reconstructed contiguous payload and remain bound to
the separately validated metadata/authority identity.
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

Compression-result qualification must exercise the signed target boundary with
positive, zero, and artificial negative results. When an error wins prepared
publication, it must retain its exact errno, must not increment RAW-fallback
accounting, and must not publish or stage RAW as a no-fit result. When
RAW_SELECTED linearizes first, a late negative result must leave that selected
state unchanged, must not be counted as codec no-fit, and must fail the target
closed as soon as the producer observes it. The selected RAW lower write may
overlap speculative compression, but successful upper ACK must wait on the
producer's result completion while the consumer retains its prepared-page
reference. Qualification must prove the ACK waiter remains blocked until that
completion, returns the exact late negative errno, permits a nonnegative late
result, and bypasses the wait for an already-terminal READY representation.
Source ordering must place this barrier before both synchronous success ACK and
detached-run success publication/defer delivery; generic/preempt-disabled
completion paths must not sleep. Prepared and ordered owners are separate
required cases; the ordered mapped-input case must prove unmapping precedes the
error return. Positive and zero controls must continue to select compressed and
RAW storage respectively.

Direct codec qualification must include deterministic nonzero randomized
payload bytes, boundary lengths around 8-byte/CRC lanes and production packing
cliffs, the maximum accepted payload, deliberately unaligned extent/payload
addresses, and every stored encoding. These cases supplement, rather than
replace, the full-page structured/entropy predictor corpus and independent
scalar/SIMD transform/shuffle oracles.

Distinguish the stored-byte *envelope* oracle from a complete compressed page
roundtrip: arbitrary record payload bytes verify descriptors, CRC, bounds and
unaligned serialization but are not themselves valid LZ4 streams. The native
predictor qualification must additionally compress real pages under each
LZ4/DELTA64/DELTA64_SHUF8 representation, persist them through the exact
production SWZ codec, verify the stored CRC/encoding/length, decompress LZ4,
invert the selected transform, and compare all 4096 original bytes. Require
nonzero successes and genuine no-fit controls for every encoding. Keep all
compression, transform, decompression and extent buffers non-overlapping.

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
sequence is checked against the extent-sequence index before payload lower I/O;
provisional coalesced blocks
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
For the **current** dedicated SD-card production mission, physical execution is
owner-authorized by the standing scope in AGENT_CONTEXT. The historical
one-use `physical-swap-probe.py` protocol below records the older
`/dev/sda4` correctness-smoke workflow and its consumed approvals; those
human-approval mechanics are not a current gate for repeated work on the
dedicated `/dev/sda1` card. Its device-identity, provenance and fail-closed
techniques remain useful patterns.
Rootless qualification must exercise the production formatter decision path
with synthetic descriptor/kernel operations and identity tables. It must cover
malformed PARTUUIDs, numeric overflow and single digits exceeding small
numeric bounds (for example removable=2 when maximum=1), copied cloneable
identifiers with a
different opened device/parent, replaced path/PARTUUID aliases, wrong opened
device, wrong parent or geometry, a changed major:minor after reconnection,
non-removable/held topology, missing sole-partition status,
parent-model/USB-transport mismatch, an opened descriptor that becomes
read-only, invalid SWZ UUID/reserved bytes, stale identity immediately before
the write, truncated reads, unexpected permissions, USB/transport-style I/O
failure, and device disappearance before and after the write. The mountinfo parser must accept normal major-zero pseudo-filesystem
entries (including `0:0`) while still rejecting malformed/overflowed rows;
major zero must remain forbidden for a configured physical partition or parent.
For every ownership/identity uncertainty before publication, the test
must count zero destructive header writes. Rootless mocks must cover protected
root-owned selector absence, mismatched PARTUUID, permission denial, and selector
revocation at the last prewrite gate; these checks must precede any read-write
device open or write. It must also prove exact valid-header repeat formatting
performs no write, zero-header initialization attempts exactly one header
`pwrite()`, a partial `pwrite()` is not resumed, and every failure after the
publication call is issued has the explicit status-3 `UNCERTAIN`/recovery
disposition rather than being reported as an ordinary no-write failure.
Post-write readback/identity failures are never success, unknown nonzero block
zero remains a recovery condition, and the standalone formatter contains no
DISCARD/TRIM behavior. A focused removable-media identity binary must cover
copied identifiers, alias replacement, parent/geometry drift, holder/activity
conflicts and reconnection repinning without opening any host block device. Source contracts
continue to verify the kernel opt-in superblock gate, reserved data offset, and
exclusion of block 0 from all data/discard paths. Exact-current-main must still
pass ordinary `make test` before any physical-media evidence is considered.

The primary manager's PARTUUID direct-C tests must reject all-hyphen,
leading/trailing-hyphen and consecutive-hyphen values, require at least eight
hexadecimal digits, preserve GPT-style hyphenated values, and prove canonical
lowercase normalization. This is a Codex-owned integration requirement; the
standalone formatter tests do not authorize edits to primary-manager source.

The standalone CLI requires the complete partition/PARTUUID/geometry/removable-
parent identity bundle documented in coding_standards.md. The older private
physical-swap correctness probe remains historical machinery; do not relax the
standalone formatter or repurpose that helper for production lifecycle
activation merely to preserve its former formatter argument list.

A separately owner-authorized physical swap-partition correctness smoke is
implemented only by the private tests/tools/physical-swap-probe.py helper. It
is never called by make test and does not qualify performance, endurance or
general physical-media behavior. Owner-provided make test reports are read
and verified; do not rerun make test or make fast_test for this physical
smoke.

#### Physical admission and qualified-artifact policy

Physical admission is bare-metal x86_64-only. Before qualification evidence is
accepted, the helper must establish that neither VM nor container execution is
active with `systemd-detect-virt`; missing or inconclusive detection blocks
admission. It requires a clean, synchronized main,
ancestry from the canonical GitHub main, and at least one complete owner
five-stage PASS report for the latest qualified production source. That report
must identify the exact source in both source_sha and tested_commit_sha,
match the live x86_64 host identity, show all five stages passed, and publish
usable SHA-256 hashes for swapzctl, dm-swapz.ko and device-roundtrip.

Earlier successful owner x86_64 qualifications count as repeated evidence for
the same production implementation only when all three artifact hashes are
identical to the latest qualification. Distinct-content reports are read from
the committed first-parent test_results.json publication history and must
match the live host. A different source SHA is allowed for these earlier
reports; a different artifact hash is not. At least one report for the latest
qualified source remains mandatory.

After the qualified source, admit only changes to
tests/tools/physical-swap-probe.py,
tests/runtime/native/physical-swap-probe-test.py,
docs/testing_standards.md, docs/ROADMAP.md and report-only
test_results.json publications. Reject merge commits and every other changed
path. In particular, any change to src/, tests/tools/device-roundtrip.c,
build rules or another qualified-artifact input requires a new owner
qualification. This exemption is only for physical-admission policy,
regression and documentation work that cannot alter the three binaries.

Immediately before the physical run, rehash the live artifacts and require
exact equality with the latest owner report. Snapshot those same bytes under
the persistent recovery directory, rehash the snapshots and execute/load only
the snapshots. The helper itself is bound by its SHA-256 and current Git commit.
The current helper-policy commit must have green non-privileged GitHub CI
before the read-only plan can authorize a run. CI does not replace owner
qualification.

#### Verbal-review record

The review record remains strict JSON and rejects duplicate keys. It must bind
approved: true, approval_mode: verbal, reviewer
openai-chatgpt-external-reviewer, the exact approval text below, the latest
qualified production source SHA, current helper Git commit SHA, helper SHA-256,
formatter/module/oracle SHA-256 values, exact repeated
/dev/disk/by-uuid/... path, partition major:minor, PARTUUID, exact byte size,
original full 4096-byte header SHA-256, a unique 32-character lowercase hex
run_id, and scope physical swap backing correctness smoke only.

> Approved for one bounded physical swap-partition correctness round-trip only, provided the exact qualified artifacts remain unchanged, the current helper-policy commit passes its non-privileged CI, the selected partition passes every read-only identity/safety check, recovery state is durably stored on persistent media, and the helper restores and verifies the original swap partition before completion. Any mismatch, unexpected state, or recovery uncertainty voids this approval and requires the run to stop.

Verbal approval is procedural. The JSON binds the supplied wording and exact
run/device/artifact state, but it does not cryptographically authenticate the
speaker or provide cryptographic proof. No .sig, SSH signature, signer key or
/etc/swapz/physical-review.allowed_signers is used. The helper permanently
consumes each run_id before state preparation, retains its consumed record
after success, and serializes each PARTUUID with a permanent lock inode and
durable active-recovery marker.

#### Read-only plan and device safety

Before run, inspect the helper's read-only plan output field by field:
device preflight, qualification/source, live artifact bytes, verbal review,
unconsumed run ID and recovery storage must all be positive. A successful
process exit alone is insufficient. The selected object must be the explicitly
repeated by-UUID path resolving to one real partition with a valid persistent
PARTUUID and matching by-partuuid link, Linux swap identity, exactly one
matching active swap entry, zero used KiB, no mounts or holders, and no
dependency in the root filesystem backing chain. The original block zero is
read through an opened and identity-checked block descriptor; BLKGETSIZE64
must match the reviewed exact geometry.

The fixed recovery base /var/lib/swapz/physical-recovery must be root-owned
mode 0700 beneath root-controlled non-symlink parents, on a verified persistent
physical-block filesystem and not on the selected swap partition. If absent, an
operator may create only this fixed base with root ownership and mode 0700; the
helper then validates the complete backing chain. Volatile, network, loop/RAM,
zram, null_blk, overlay and selected-swap recovery storage is rejected. The
state directory is a nonexistent direct child named
swapz-physical-<run_id>. Fsync the parent after its creation, then fsync the
exact original 4096-byte backup, state, reviewed binary snapshots and
directory entries before swapoff or any block-zero write. Failed durability
must stop before destructive work and preserve uncertain records.

Keep the existing fail-closed protections: exclusive and identity-checked
block-zero reads/writes, major:minor and geometry checks at every destructive
boundary, persistent PARTUUID checks, root/mount/holder checks, descriptor-
and-geometry-bound formatting, exact SWZ header validation, post-swapoff
inactivity verification, exact helper-owned mapper UUID/table/16 MiB geometry
and lower major:minor, oracle verification of its independently opened DM UUID,
conservative module ownership, and no force-removal. Unknown or torn headers
require manual recovery. Never activate the SWZ mapper as system swap.

#### Bounded positive physical correctness suite

The first oracle invocation remains exactly
device-roundtrip <mapper> --expect-dm-uuid <exact-generated-uuid>. It performs
the ordinary 128-page byte-exact write/read/overwrite/flush verification and
independently verifies its opened DM UUID before writing.

Only if that passes, run these existing positive correctness modes in order on
the same helper-owned mapper. Immediately before and after every invocation,
reverify the exact mapper UUID, table, 16 MiB size and lower backing. Record
dmsetup status and the selected partition block-stat snapshot before and
after each phase where available.

1. Delta64: --delta64-write-series 128 1, then
   --delta64-verify-series 128 1.
2. Segmented/multi-bvec: --segmented-write-series 128 5, then
   --segmented-verify-series 128 5, then --verify-series 128 5.
3. Cross-representation: --write-series 128 6, then
   --segmented-verify-series 128 6.
4. THP/compound-folio: --thp-write-series 128 7, then
   --thp-verify-series 128 7, then --verify-series 128 7.

This first physical round excludes performance and endurance measurement,
failure injection, fault ordinals, DISCARD/TRIM, repeated 4096-page rewriting,
GC or resource pressure, null_blk-only overrides and timing-dependent
suspend/drain work. A failed phase stops all later phases and immediately
enters the normal recovery path. Do not retry a failed phase under the same
approval or create a replacement approval automatically.

#### Durable results and restoration

Before destructive work, persist a bounded results.json in the recovery
directory. It records start/end timestamps, Git/helper/source and artifact
hashes, run/device identity, original header digest, original swap size and
priority, mapper name/UUID, per-phase command/return code/bounded stdout and
stderr, before/after dmsetup status, block-stat snapshots where available,
final block-zero digest, final /proc/swaps row, recovery state, and mapper,
module and unrelated-mapper cleanup observations. Never store raw page
contents. Update and fsync the record throughout execution so failure evidence
survives recovery.

Only the helper's run path performs the destructive sequence. It exclusively
locks the partition, consumes the one-use approval, saves and fsyncs recovery
state, revalidates source/artifacts/device, disables only the selected zero-use
swap partition, formats through the reviewed descriptor-bound formatter,
loads only the snapshotted module with physical backing explicitly enabled,
creates and verifies one helper-owned 16 MiB mapper, and runs the positive
suite. On success or failure, remove only that exact mapper, unload only a
positively same-process-owned module, accept only a recognized recovery
header, restore and reread the exact original 4096 bytes, reactivate only the
original partition with its original priority, verify its major:minor/size/
priority, durably mark recovery COMPLETE and release the active marker. Keep
the consumed-approval record and all recovery artifacts.

Before declaring the smoke complete, prove every selected phase passed; the
helper mapper is absent; unrelated mapper inventory is unchanged; the
helper-owned module is unloaded when safe; block zero matches the original
digest; the original swap entry is active with the same major:minor, size and
priority; recovery state is COMPLETE; no active marker remains; and the
approval remains consumed. Post-reactivation swap usage is an observation.

#### Physical-swap rootless regression gate

For final `results.json` observations, compare the active original swap
entry against `swap_size_kib` and `swap_priority` in the durable saved
recovery state, not the identity-only recovery target (which contains
neither field). Require the row to identify the original active partition,
and do not require zero usage after normal swap is re-enabled. Missing or
inconsistent saved values must not produce a verified-restoration result.
Preserve historical incident evidence even if an old results file contains
a false negative.

When `journalctl --kernel` is unsupported or fails, attempt a read-only
`dmesg --time-format=iso` fallback and bound the recorded swapz lines.
Explicitly record that the dmesg fallback is **not time-filtered**;
messages found there may predate the physical attempt and cannot be
attributed to it without independently checking timestamps. Retain
the journal failure reason, and report unavailable if both sources fail.
Do not hash the full active swap partition during post-recovery checks;
read only the identity-checked original 4096-byte header.

All `dmsetup info -c` consumers must interpret colon-delimited and
whitespace-delimited rows with exact expected column counts. An existing
owned mapper must never be interpreted as absent because a separator
changed. Require exact owned name and UUID in both the inventory and
existence checks, and exact name/UUID/major/minor plus sysfs/table/size/
lower-backing identity in mapper verification. A wrong UUID under the
expected name or the owned UUID under another name must fail closed.
A failed Device Mapper enumeration must never be treated as absence;
the first mismatching row must stop recovery without a second probe.
New mapper-name allocation must use the same checked decoder to detect
existing name/UUID collisions, including colon-delimited report rows.
The standalone recovery path must continue to refuse module unloading
without same-process ownership; a recovered parser is not permission to
bypass that limitation.

The helper's read-only Device Mapper inventory must treat a successful
`dmsetup info -c --noheadings -o name,uuid` response containing only the
exact `No devices found` diagnostic (surrounding whitespace allowed) as an
empty inventory. The normalized empty inventory must hash identically
before and after the bounded run. A command failure, blank response,
extra diagnostics, or malformed mapper rows must continue to block.
Rootless regression must cover the empty-inventory response, malformed
variants, nonzero exit, and unrelated-mapper identity/hash preservation.
The complete synthetic run must call the inventory snapshot again after
simulated owned-mapper cleanup and compare that result with the initial
snapshot; it must not copy the initial fingerprint into the final record.

Keep tests/runtime/native/physical-swap-probe-test.py in the existing
rootless safety regression path; do not wire the private helper or a real
device into routine make test. Rootless tests use temporary files,
controlled command mocks and operation-order assertions only. Cover the
latest-source PASS plus matching-artifact history policy, allowed post-source
paths and merge rejection, live artifact hashes, exact verbal-review fields,
duplicate-key rejection and replay, selected-partition exclusion from
persistent recovery storage, durable backup/results boundaries, every mapper
identity check, phase ordering/status capture, stop-on-first-failure behavior,
module ownership and exact restoration. Keep current sysfs/FD limitations of
mocks explicit: rootless evidence does not establish physical-media behavior or
replace the real read-only device plan.

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
960s. Rootless source contracts that audit the loaded wrapper must pin this
same 960s ID36 bound everywhere; a stale generic 720s pair bound must not make
qualification fail before the loaded stage. ID36 additionally keeps its internal 840s pair watchdog and two 280s
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
A missing/invalid identity fails closed. Legacy reports without identity stay
excluded unless their immutable report SHA is explicitly owner-confirmed for
that computer in `docs/handoff/host-history.json` and passes that entry's CPU,
backend and five-stage checks; included legacy points are labeled with that
provenance in `history.json`. The plotter also creates `legacy-candidates.json`
for unidentified PASS reports with matching architecture and online CPU count
plus at least one overlapping executed backend. Matching kernel evidence ranks
candidates higher. The stable index links this file and lists candidates for
review, but candidate discovery never pools a report. A full report SHA must be
added to the generic registry with an owner-confirmation record before it can
join a host's history. Report SHAs assigned to another registered host are not
suggested again. ISA/CPU count alone cannot migrate reports. After the
exact-computer refresh, the ARM64 host also refreshes its pre-existing
NEON/seven-CPU legacy-cohort history separately under
`build/history/arm64-neon/`. ARM reference refresh failure is reported
separately and cannot alter qualification. OS reinstalls start a new history,
and cloned installations must have unique machine IDs. Python Matplotlib must
be installed for rendering.
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

The x86 i7-1185G7 audit and its owner-confirmed legacy SHA are recorded in the
generic `docs/handoff/host-history.json` registry, alongside the inspected CPU,
kernel, virtualization, firmware-memory inventory and backend details. That
entry adds the confirmed legacy report to the matching exact-identity history
and tags its report SHA. Selection requires all five stages PASS, the audited
eight-CPU count and scalar/SSE2/AVX2/AVX-512 execution evidence. Other computers
use the same registry schema; they do not inherit the x86 profile. Verify
legacy host/protocol before adding a SHA; backend names and CPU count alone do
not establish the same physical machine.
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



### Idle-lane submitter dispatch and ID169 qualification

Native window-policy tests cover every input of
`swapz_window_submitter_dispatch_ready()`; native authority tests prove
`swapz_open_segment_fits()` is read-only, refuses an unopened, exhausted, GC,
staged or batch-pending cursor and illegal classes, and that whenever it holds
the real stage path places at the cursor without calling the recycle hook.
Source contracts pin the mapper trylock (never `mutex_lock`) before
`queue_lock`, the hint gates, FIFO-head restoration on decline, the forced
detach and `-EUCLEAN` no-sync guard in `swapz_flush_window()`, no wait/GC/
flush/discard call in the dispatch body, mutex release before the lane return,
the worker's whole-pass ownership with private-list delivery after release, and
the ID169 `lower_write_active` guard before any claim state. The completion
probe executes the actual list-delivery body. Replay and report validators
require `submitter_dispatches + submitter_dispatch_declines <=
submitter_prepare_claims` and zero activity when submitter preparation is off.

These checks support review only. Exact-source owner `make test` must pass the
loaded lifecycle, suspend/drain, retained WRITE fault, GC and ID36 gates with
the defaults on. QD1 service evidence requires positive timed
`submitter_dispatches` in sustained QD1 arms; QD4+ and mixed rows must not
regress lower bytes/requests or p99 beyond their guards. ID169 and ID175 change
disjoint regimes (active versus idle lower lane), so attribute QD8 movement to
ID169 and QD1 movement to ID175 only directionally, never causally from one run.

### Per-device-class goal scorecard and plots

`tests/tools/product_goals.py` is the single classification shared by the
reporter and the history plotter. Device-bound classes (serial/fast/SD/SATA
mixed, serial QD4/8/32, fast QD8/32) must beat raw useful WRITE and save lower
WRITE bytes and requests. Latency-bound (serial QD1, fast QD1/QD4) and
host-bound (NVMe Gen4/Gen5 mixed) rows are guards within 5% of raw that must
not add lower WRITE work. `test_results.json` records
`benchmarks.goal_scorecard`; the console prints one compliant table. Missing
inputs are UNAVAILABLE, never zero. The scorecard is descriptive: no gate,
exit code or publication decision may read it. Rootless tests cover target and
guard edges, epsilon, latest-point selection, persistent-row lower-I/O
derivation, table width and the plot goal helpers.

Gain plots title every panel with its class goal and draw the guard floor only
on guard panels; latest-value captions sit below each axis so no point is
hidden. The per-computer `index.md` carries a valid GFM summary table and the
latest scorecard. History refresh keeps its bounded per-helper timeout
(600 seconds) because every refresh re-reads all committed reports.

### Independent-target stripe development experiment

The `*-stripes` `make fast_test` scenarios are the development-only test for a
possible single-lower-WRITE-lane ceiling. They do **not** alter production C and
never enter `test_results.json` or qualification history.

The existing NVMe5/SATA study uses a persistent mixed QD32 trace with WRITE
and immutable READ pages owned by a lane. The separate fast-model study uses
the identical production service envelope as the ordinary fast 80 MiB/s,
150-us synthetic lower, but persistent WRITE-only QD4 or QD8 with the existing
fixed-lane native engine and immutable 256-warmup/4096-measured-operation trace.
For N=1,2,4, each selected workload is partitioned exactly by
`logical_page % N`. It renumbers only each target's local page/lane/sequence;
the fixture payload selected by every original operation is preserved. A
stride/offset prefill map preserves the original initial bytes after local-page
renumbering, and every child plan passes the ordinary complete-image oracle.

Each arm owns N separate RAM-backed `null_blk` devices. The swapz arm creates N
independent ordinary K=1 targets, one per lower. The raw arm uses N equally
modeled lower devices with the same page-to-stripe mapping. Aggregate offered QD stays 32 for mixed and 4 or 8 for the corresponding
fast WRITE workload; each target receives QD/N. Per-device bandwidth is the
model bandwidth divided by N (80/40/20 MiB/s for fast); per-device hardware
queue capacity is divided by N while preserving the model's submission queue
count (64/32/16 for fast), so aggregate modeled bandwidth and queue capacity
do not grow with N. NVMe5 remains the original mixed primary model and SATA
its secondary control; fast WRITE QD4/QD8 are distinct model/workload cohorts
and must never be pooled with mixed QD32.

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
`striped_target_experiment`, including exact workload/QD, host-load profile,
trace provenance, logical throughput, lower bytes/requests and worst-stripe
WRITE p99. The next development invocation overwrites `latest.json`:
operators must preserve separate run artifacts for cross-policy comparisons.
The rootless oracle reconstructs every parent op, page, lane and payload from
each child for N=1/2/4 at QD4 and QD8, and both-arm loaded validators require
the expected replay mode, QD/N and zero reads for write-only mode.
Do not infer K=2 benefit merely from target-count scaling: splitting independent
targets shrinks each target's packing opportunity. Nor does a positive N=2
result identify owner serialization: stripes change owners, batching domains
and targets together, so it shows only that more independent execution can
raise normalized service (ROADMAP ID176). A reopen requires a material
improvement in normalized swapz/raw useful WRITE service, preserved lower-byte
savings, and observed simultaneous swapz lower WRITEs for N>1.

### Development-only hand-threshold A/B

The early work-conserving hand retains its production eight-record threshold
unless the private `make fast_test` loop explicitly selects 16 or 64 through
`HAND_RECORDS`. The module parameter is read-only. Target construction rejects
values outside 8/16/64; a nondefault value additionally requires retained
asynchronous preparation and identified `null_blk` backing. The private pair
checks effective DM status before replay. `make test`
remains at eight and does not add a new qualification pair or historical cohort.

Compare matched same-source, same-model, same-trace sustained Fast-QD32 and
Serial-QD32, `SUBMITTER_PREPARE=1` versus `0`, counterbalancing
`HAND_RECORDS=8,16,64` development pairs. Preserve per-arm useful WRITE,
p99, independent lower bytes/requests, windows/pages per physical request,
early-hand closes, idle attribution, ready-run wait, and host busy/PSI/quiet
screens. Use the exact byte oracle. Do not pool noisy or cross-host controls.
A larger threshold is not permission to wait for future arrivals, suppress a
valid four-record boundary or open a second lower-WRITE owner. The hypothesis
fails when increased pack size does not improve useful throughput alongside
lower-I/O and latency guards. Any retained production candidate requires full
same-source owner `make test` correctness, lifecycle, fault, resource-pressure
and product workload qualification.

The fixed old-PC production-stack hand8/16/16/8 pilot reduced window
fragmentation and lower-WRITE requests but did not establish the required useful
service: fast-QD32 accepted-work idle increased while the normalized throughput
interval crossed zero. Preserve the eight-record production threshold; do not
promote or collect replacement observations to resolve this pilot's failed
service/guard evidence. Threshold64 and submitter-off interactions were not
tested by that pilot and remain separate questions. Any new threshold experiment
needs a distinct prospective mechanism and fixed protocol.

A dispatch candidate that flushes before a submitter-owned FIFO head must keep
that head queued and untouched, serialize the existing prefix publisher, and
preserve K=1 and the four-record floor. Direct helper tests do not replace
whole-worker/lifecycle qualification. The fixed ID165 pilot rejected this
specific change: it split useful aggregation, missed the fast-QD8 useful-service
target, and violated lower-WRITE request guards. A submitter deferral is not
automatically removable idle, and lower idle or more early hands cannot override
failed service/request guards. Reopen only for a distinct measured mechanism
that preserves useful aggregation. Keep rejected C/probes only in local
experiment artifacts and immutable history, outside active product code.

Submitter wake-suppression experiments must retain the worker's locked
ownership recheck before FIFO handback; removing it permits a lost wake. Tests
must cover release before that recheck, during FIFO handback and after handback.
A negative control removing the recheck must fail the lost-wake assertion.
Controlled interleavings do not replace LKMM/concurrency and loaded lifecycle
gates. ID166's visible queued-head suppression variant did not establish either
a useful-service gain or an owner-deferral reduction and was removed. It
preserved the empty-incoming wake, so it did not test suppressing wakes while
the ordered worker owns a private local FIFO.

Empty-incoming wake suppression needs release-before-recheck and
release-during-handback cases with a private local FIFO, plus retained and
nonretained ready-head wake checks. The ID167 private-FIFO pilot failed its service/deferral targets and is
removed. Generic deferral counts are not proof of unnecessary wakes; do not
add another wake predicate without evidence attributed to a specific
unnecessary-wake population and a complete progress proof. Any future wake
policy must preserve ownership and may not change packing to manufacture a win.

Preparation placement comparisons must keep the production compression stack
on and account for each timed WRITE across submitter, producer and ordered
preparation exactly once. ID169's lower-WRITE-active bypass is now production
after the owner's later promotion of the frozen guard: guard/resource tests
must prove it returns before lane/page ownership and preserves the established
mapper fallback. Independent confirmation remains a fixed historical cohort:
declare its count and acceptance bounds before collection, keep the exact
candidate hash, and exclude pilot data from confirmatory inference. Pinned
source owner qualification remains mandatory.

The completed ID169 confirmation passes its QD8 primary and QD8/QD32 guards,
while the fixed shorter mixed cohort has only 11 usable comparisons from five
cycles, below the declared 12-comparison/six-cycle minimum, with service and
p99 bounds unresolved. That confirmation alone did not authorize retention.
The owner later promoted the same frozen guard after exact-source x86 and
ARM64 `make test` PASS results; mixed service, lower bytes/requests and p99
remain watchpoints, and an exact-source owner run must reject the guard if
those regress beyond their guards. Preserve all excluded observations; do not
extend the completed fixed sample or relax its screen after inspection.
Pre/post CPU counters cannot identify task ownership or establish operator
activity. Any follow-up protocol must address the coverage limitation prospectively.

The development loop may set `MIXED_OPS=65536` for ordinary mixed-only
scenarios, extending the deterministic 16384-operation measured stream fourfold
with the same 1024 warmup operations, fixture, QD and generator seed. Both arms
consume one immutable plan and must pass the ordinary complete-image oracle.
The default remains 16384; WRITE-only, striped and calibration comparisons
reject the nondefault selector. Reports identify `mixed_measure_ops` and the
actual per-arm operation counts and trace hashes. Longer traces form a separate
cohort: never pool them with ID169's completed confirmation or reinterpret
that result. Quiet-host/raw-drift screens and source/ordering checks remain
unchanged. A longer trace can improve tail sampling and amortize interruptions;
it cannot prove an idle host or eliminate the need for fixed prospective guards.
The nested rootless replay-suite watchdog is 90 seconds (formerly 40) to cover
the measured ~44-second suite including the longer deterministic-plan oracle
checks on the two-core host. This changes no loaded replay, privileged helper,
kernel-progress or teardown deadline.

Prepared compression-cost coverage must execute the actual production wrapper
and ordered observer against the existing EWMA helper. Check a nonzero lane
baseline, consecutive compressed/RAW samples, a zero/unknown sample, preserved
encoding/zero outputs and the complete mutable-state exclusion. A protected
mapping must cover the full prepared object: testing only its first page could
miss an invalid timing-field read beyond that mapping. Compiled mutants using
cumulative lane time or removing the READY guard must fail. Source wiring must
cover both asynchronous owners and publication before READY; loaded evidence
must show a nonzero estimator with submitter claims and zero inline work.
ROADMAP ID 171's rejected early-snapshot pilot passed bounded two-reference
ownership probes (including descriptor-poison/ASan/UBSan coverage), but missed
the 5% service floor and increased lower bytes beyond the 1% guard; control C
was restored. It does not authorize early descriptor release or a second
submitter reference. Its zero asynchronous-LZ4 EWMA observation motivated
ID172's estimator-coverage repair; that observation does not retain ID171.

Prepared-state native qualification must inject producer READY_COMPRESSED and
READY_RAW publication between the consumer's initial PREPARING read and its
RAW-selection compare/exchange. The failed-CAS shim uses relaxed failure
ordering, matching the kernel API's lack of an acquire guarantee. Require an
acquire observation of READY before metadata consumption; already-READY and
successful RAW claims keep one acquire read. A compiled relaxed-reread mutant
must fail. These API-level interleavings and threaded reuse checks are not an
LKMM proof or an observed weak-memory hardware failure. A retained production
change still needs exact-source owner qualification with the full codec stack.

## Experimental live-swap supervisor

The experimental live-swap coordinator is separate from the historical
physical-backed correctness helper. The old `/dev/sda4` trial and its one-use
owner waiver remain historical evidence. For the current dedicated SD-card
mission, standing owner authorization in AGENT_CONTEXT replaces another
per-run owner/external-review decision. Privileged lifecycle actions still
remain fail-closed until their exact implementation has the required
source/recovery tests, current exact-source qualification, current CI and live
device-identity/ownership gates.

The primary boot-manager package currently installs its systemd units disabled;
package installation must never start the mapper, activate swap, or enable a
unit. The native `swapzctl primary` privileged actions must remain blocked by
the explicit execution gate until their lifecycle is qualified. The manager is
not eligible for use as the machine's primary swap until
it has a complete durable provisioning and restoration path, interruption-safe
startup rollback, mapper/module ownership checks, rootless lifecycle coverage,
and exact-source qualification. Installing the manager or passing its parser
and geometry tests does not establish readiness. Keep the boot units disabled
until live swap, orderly shutdown, recovery and boot lifecycle gates have been
verified on the exact host and device.

The live-swap trial is the owner-waived, no-fallback trial described in
[live-swap-trial-recovery.md](live-swap-trial-recovery.md). This paragraph and the fixed `/dev/sda4` geometry that follows are a
historical old-host record, not the current production-target contract. Current
target identity, no-fallback decision and completion criteria are in
AGENT_CONTEXT. It is limited to one
mapper at the maximum logical capacity admitted for the complete `/dev/sda4`
partition (3,727,872 pages, 15,269,363,712 bytes) and to 30 minutes, with one
bounded cgroup swap-pressure check inside the window. Admission requires the
exact bare-metal x86_64 target, unchanged qualified production artifact hashes,
clean synchronized `main`, current non-privileged CI for HEAD, the original swap
as the only active swap area at priority -1, no conflicting mapper, module or
recovery owner, durable recovery storage, RAM use below 50 percent with enough
MemAvailable to drain the current swap, conservative memory and PSI gates, and
one unconsumed approval record. No fallback swap is required or created. A
`verbal` approval needs an external reviewer record. The `owner_waiver` mode
replaces that record for this one trial and states that no reviewer approval
exists.

Rootless tests for this procedure pin device identity with synthetic
major:minor values, so they never depend on a block device on the host (CI
runners have no `/dev/sda4`). Rootless tests for this procedure are software-model evidence only. They do not
qualify Linux `swapon`, physical performance, cold-boot recovery or power-loss
behavior. The owner objective for this PC excludes VMs. Keep these limits
explicit in every review and result.

The primary manager's direct production-C tests must exercise multiple synthetic
target identities and geometries, Device Mapper output variants, active-swap
parsing, header recognition, and fail-closed ownership decisions without
opening or modifying a block device. Include different major:minor values,
minor zero, different PARTUUIDs, and capacity/alignment boundaries so tests do
not encode the active owner's current partition as a production assumption.
The direct-C fixture must compile the plan in a mode that refuses all host
block-device and `/proc/swaps` reads; test the identity and signature parsers
with synthetic major:minor values and bytes. Host admission must hash the exact
4096-byte block-zero image and compare it with the transaction's manifest-bound
digest before any destructive transition; the selected partition need not have
contained a Linux swap signature before provisioning.
The plan must also check the fixed recovery base's root-owned 0700 path, an
allowlisted persistent filesystem, direct filesystem-device separation from
the runtime-selected target, and absence of that target's PARTUUID marker.
Separate recovery-source and
target-source gates must resolve each device through `/sys/dev/block`, match
the recorded major:minor, prove a direct physical partition with a physical
parent device, and reject holders, stacked slaves, virtual devices and the
selected swap partition in the recovery chain. Keep Btrfs excluded until
multi-device backing can be enumerated and checked. Report whether recovery
storage shares the target's physical disk; that is a relevant failure-domain
limitation even when it is a different partition. Rootless tests must use
synthetic sysfs trees and cover malformed device numbers, target identity,
missing physical identity and nonempty holder or slave directories without
reading host block devices. Parse mountinfo strictly, identify the unique `/`
mount, verify its physical source chain excludes the selected swap partition,
and reject any mount whose major:minor is that partition. Rootless mountinfo
tests must include escaped mountpoints, special non-path filesystem roots,
malformed device fields and duplicate root entries. The plan must also inspect
`/sys/module` and `/sys/block/dm-*`, failing closed on unreadable or malformed
entries, any loaded `dm_swapz` module, or any mapper name/UUID in the `swapz-` /
`SWAPZ-` namespace. Rootless tests must cover valid `dm-N` enumeration names,
malformed names, matching name and UUID prefixes, and unrelated mapper
identities without loading modules or querying the host inventory.
The `/proc/swaps` parser must reject malformed or extra fields, duplicate paths,
numeric overflow and invalid signed priorities. The read-only plan may report
the active-entry count and whether the configured PARTUUID's discovered device
is the sole partition entry at the size derived from its physical byte capacity,
at the selected priority and with zero KiB used; this partial observation must
never be reported as complete device admission.
The package regression must prove that units are installed disabled and that
package install/uninstall does not start or stop system swap. Assert executable
systemd directives and generated dependencies, not descriptive unit comments;
the mapper unit must require the persistent physical-recovery mount before its
preflight/recovery/prepare chain. The package-owned
file set and SHA-256 manifest must include the cold-boot verifier executable
(mode 0755) and verifier service (mode 0644); uninstall must reject modified
copies and remove only exact owned copies. Installation must substitute the
installed sbin path into both lifecycle services without enabling or starting
either one. The isolated systemd verifier fixture must run from the official
rootless contract stage, covering arm/preflight/observe success and fail-closed
raw-alias, identity, artifact, geometry, service and kernel-log cases without
reading or changing host swap state. The primary mapper service and package
templates must not contain a device pathname,
major:minor, UUID or PARTUUID. The installed systemd generator must derive
the selected `.device` and by-PARTUUID `.swap` unit names through the manager's
validated protected-selector interface, then emit `Requires`/`After` for the
device and `Conflicts`/`Before` for its by-PARTUUID swap unit. The exact
selected `.device` job must have its own 30-second timeout, while the mapper job
has a separate 300-second bound so the manager's bounded startup and shutdown
(including native swapoff) are not truncated by device-discovery policy. Rootless
package coverage must assert both generated drop-ins independently. It must not
use `BindsTo` on the removable device, because
media removal must not automatically stop a mapper that may own live swap
pages. Rootless package tests must use at least two selected PARTUUIDs and
verify the generated names and dependencies change, and malformed selector
output must fail without emitting a drop-in. These dependencies are not a
complete activation policy: a raw swap entry may be named by UUID or another
alias, so deployment must separately ensure the selected partition is not
activated through that alias. Current units remain disabled and
`RefuseManualStart`/`Stop` stays in force until the full lifecycle and boot
path are qualified. The manager must use the same
permanent selected-PARTUUID lock for all of its operations; tests must reject
an unsafe lock directory, lock file or concurrent owner before any mutation.
A persistent active-ownership marker is also required before the provisioning
path can be enabled.
The native lock primitive must open the same permanent
`partition-<selected-partuuid>.lock` inode under
`/var/lib/swapz/physical-recovery`, reject symlinks and unsafe ownership or
modes, acquire a nonblocking exclusive `flock`, and fsync the recovery-base
directory. It must never unlink or replace that inode. Until lifecycle commands
actually acquire and hold this lock for their full operation, the primitive's
presence alone does not satisfy the manager's shared-lock requirement.
Before the first device mutation, consume a fresh lowercase 32-hex run ID with
an `O_EXCL` record and create the matching active PARTUUID marker. Each record
must be root-owned mode 0600, fsynced, and followed by a recovery-directory
fsync. A partial or uncertain claim stays consumed and blocks future starts.
Only checked recovery after a durable COMPLETE state may release the active
marker; consumed records remain permanently present.
Mutable lifecycle state must use a root-owned 0600 temporary file, bounded
record size, file fsync, identity-checked atomic rename and recovery-directory
fsync. Reject symlink or non-regular replacement targets, and fail closed if
the durability step is uncertain. Rootless direct-C tests must update an
existing record and preserve it when a symlink target is presented. The
stable boot state is `/var/lib/swapz/physical-recovery/primary-state.json`,
on the already-validated recovery filesystem. Package removal must refuse
while this file or the active ownership marker exists, including dangling
symlinks at either path; both remain preserved until an explicit completed
recovery. The rootless package test must cover these refusal cases.

Package admission must treat every current-kernel `dm-swapz.ko` candidate
(uncompressed or compressed) as package state even when the userspace/source
tree is absent; an unmatched image is foreign and blocks installation rather
than being overwritten. Installed source files and package-owned directories
must remain single-link, non-symlinked, owner/mode-checked objects, and existing
shared destination directories must not be group/world writable. Production
may accept distribution symlink wrappers for `dkms` or `depmod` only after
the canonical executable resolves inside a trusted system executable directory
and is root-owned and non-writable. Transaction scratch must use a dedicated
root-owned mode-0700 directory outside shared temporary directories; errors or
signals during the pre-mutation backup phase remove only that staging data,
while failures after mutation enter the full version-owned rollback path.

Recovery must refuse while any `swapoff` process runs in a swapoff stage, even
when the kernel still lists the device, and an unreadable `/proc` entry fails
closed. Rootless suites for this procedure run with privileged commands refused
(for example through a `sudo` stub that exits nonzero). The physical-swap-probe
suite simulates its physical run with mocks, so it must pass under that stub
and must never be run unguarded on the PC.

The supervisor's qualified-source and artifact pins must follow the latest
owner x86_64 five-stage PASS report, including the tested oracle binary hash.
A changed test helper or oracle requires a report for that exact source and the
corresponding live hashes; do not carry an older oracle digest forward by
assuming only the production module changed. This artifact binding does not
qualify Linux `swapon` behavior or performance.

The read-only plan may print a mutation trace, but it must never invoke the
mutation channel. `mkswap` may target only the exact verified mapper, without
force. The primary C manager must pin a root-owned `mkswap` executable that is
not group/world-writable, pass it only a descriptor path for the independently
verified mapper, and verify the resulting Linux swap v1 header, including its
exact ten-byte `SWAPSPACE2` magic, against the mapper capacity. It must also
prove that the selected target's manifest-bound original block-zero image is
unchanged before and after initialization. The formatter operation is valid
only in the durable `STARTING` state. Rootless direct-C tests must validate the
header fields and prove the privileged formatter stub is unavailable without
target mutation. `swapon` must not request discard. Never remove an active swap
mapper or unload a module while it may contain pages. A failed mapper `swapoff`,
uncertain mapper/module ownership, ambiguous header, or recovery uncertainty
leaves the mapping, module and recovery evidence in place for supervised
review. Do not create or depend on fallback swap. Do not reboot, force-remove, overwrite an unrecognized
header or retry a failed phase automatically.

Recovery-state tests must cover a second, standalone cleanup attempt
after an earlier failed recovery. When cleanup writes `TRIAL_STOPPING` over
`RECOVERY_REQUIRED`, header verification must resolve both saved wrappers
back to the original durable stage without guessing an unrecorded format.
Missing, cyclic, torn or contradictory stage provenance must fail closed
before any backing-header write. VM coverage is not part of the current project.
Exercise interruption logic with rootless state-machine tests, direct-C tests,
owned RAM-backed `null_blk` and safely bounded native-host resources. The
rootless lifecycle audit must enumerate durable STARTING snapshots before mapper
creation, after inactive mapper creation and after swapon; STOPPING snapshots
before/after swapoff and after mapper removal; RECOVERING snapshots at the same
cleanup boundaries; RECOVERY_REQUIRED; and RESTORED before COMPLETE/owner
release. Every exact-owned snapshot must converge through standalone recovery,
while a wrong mapper identity must issue neither swapoff nor remove. Source
guards must prove RECOVERY_REQUIRED is durable before RECOVERING, cleanup
precedes RESTORED/COMPLETE, owner release follows COMPLETE, and a failed
in-progress recovery durably returns to RECOVERY_REQUIRED. This deterministic
model evidence does not replace owned-null_blk/native-process interruption
qualification. The production translation unit may expose two mutually
exclusive noninstalled qualification seams. The owned-null_blk rehearsal seam
requires its dedicated test macro plus private config, recovery and
qualification-report paths; only that build may use the virtual-null_blk
topology exception described below. The physical real-swap seam retains the
production `/etc/swapz`, recovery and qualification paths, requires a
compile-time path to the installed qualified `<prefix>/sbin/swapzctl`, and
must resolve/hash formatter/module/oracle artifacts from that installed control
tree rather than from the temporary executor. Physical lifecycle commands must
also require exact runtime marker
`SWAPZ_PRIMARY_PHYSICAL_QUALIFICATION=1`; without it the private executor
remains blocked. The ordinary source must retain literal execution gate 0 and
must not read that marker. The public Makefile and package must never define,
install or expose either test seam. The source contract must inspect the root
Makefile directly and reject the physical seam macro there. The lifecycle audit
must identify the ordinary production gate independently of seam-local gate
definitions, and must prove the native swapon/swapoff syscall implementations
plus activate/deactivate routing through the shared transition ops. Its
comment/string-stripping function-body extractor must recognize the production
helpers' actual scalar return types, including `int` and syscall-width
`long`, rather than treating a valid native syscall wrapper as absent. Rootless CI
must warning-compile both seams, prove the physical seam fails compilation
without its qualified-control path, and prove both seam macros cannot be
combined. The production topology proof
still rejects every virtual backing chain. Under the owned-null_blk macro only, the
selected target may use a virtual parent when it is exactly one
`/sys/devices/virtual/block/<disk>` parent, its source is exactly one partition
child, and that parent major equals the unique `nullb` block major parsed from
`/proc/devices`; root and recovery filesystem chains keep the unchanged
physical-device proof. The official rootless stage must compile this test-only
translation-unit branch with `-Wall -Wextra -Werror -fsyntax-only` and
nonexistent private paths on every CI architecture so dormant rehearsal code
cannot rot. This seam is not deployment authorization and must never be
installed. Do not intentionally crash or reboot
the host to manufacture power-loss evidence.

The plan, lifecycle mocks and CI do not by themselves establish live-swap
correctness. Model each durable interruption boundary and add physical-host
evidence only where the test can fail without intentionally stranding ordinary
system pages or crashing the PC. Do not claim a mock proves power-loss behavior.
Document that loss of the volatile swapz mapping authority loses access to
pages already stored through that mapping. Never describe a fallback swapfile
on another partition of the same physical disk as independent-media
redundancy.

The native primary manager's lifecycle-stage vocabulary is defined in
`src/userspace/swapz-primary.h`. Its parser accepts only exact stage names, and
its transition predicate rejects every edge outside the table below. Rootless
direct-C tests cover the stage-name round trip, every ordered pair of known
stages, invalid enum values, and invalid names. Repeated persistence of an
in-progress stage is permitted; `COMPLETE` is terminal for that run. A new run
requires a fresh lowercase 32-hex run ID, a one-use owner claim and a
separately validated state transition. The canonical state record has exactly
the fields `schema`, `run_id`, `stage`, and `recovery_previous_stage`, in that
order. It has no escaped strings, duplicate or unknown keys, or trailing data;
recovery provenance is `null` for a normal lifecycle and retains the exact
original interrupted stage through `RECOVERY_REQUIRED`, `RECOVERING`, and
restored completion. Parsing and formatting must be round-tripped in rootless
direct-C tests. A same-run transition to `COMPLETE` is terminal. A later run may
begin at `READY` only from a valid `COMPLETE` record and with a different run
ID. The state-transition predicate alone does not prove the corresponding
one-use claim exists, authorize a device operation, or establish that a saved
stage matches the live device. The mutable stage envelope is not a complete
recovery manifest; durable run evidence must separately bind the exact
partition identity, qualified source and artifact hashes, and expected mapper
identity and geometry. If an optional original-header backup is recorded, bind
its digest to that run's manifest.

| Current stage | Permitted next stages |
| --- | --- |
| `READY` | `READY`, `STARTING`, `DISABLING`, `RECOVERY_REQUIRED` |
| `STARTING` | `STARTING`, `ACTIVE`, `RECOVERY_REQUIRED` |
| `ACTIVE` | `ACTIVE`, `STOPPING`, `RECOVERY_REQUIRED` |
| `STOPPING` | `STOPPING`, `RESTORED`, `RECOVERY_REQUIRED` |
| `RECOVERING` | `RECOVERING`, `RESTORED`, `RECOVERY_REQUIRED` |
| `RESTORED` | `RESTORED`, `COMPLETE`, `RECOVERY_REQUIRED` |
| `DISABLING` | `DISABLING`, `COMPLETE`, `RECOVERY_REQUIRED` |
| `COMPLETE` | none |
| `RECOVERY_REQUIRED` | `RECOVERY_REQUIRED`, `RECOVERING` |

Persisted recovery records must retain and validate the original interrupted
stage independently of this transition predicate. This table is policy
scaffolding, not a complete lifecycle implementation; it does not permit
enabling privileged commands or boot units by itself.

The native durable-state writer must hold the exact permanent PARTUUID lock,
verify the active and consumed owner records against the state run ID, parse
the existing canonical state, and reject an illegal transition without
replacing the prior file. An absent state permits only the initial `READY`
record after the one-use claim exists. A new run may replace `COMPLETE` with
`READY` only under a different claimed run ID. Releasing the active owner
marker requires a matching `COMPLETE` record and must leave the consumed record
in place. Rootless tests must cover a competing lock, representative accepted
state updates, rejected edges with byte-identical state preservation, recovery
provenance retention, fresh-run admission, and marker release only after
completion. A coordinator that has durably entered an in-progress stage must
use the recovery-required writer on any later failure: it atomically persists
`RECOVERY_REQUIRED`, preserves the first interrupted stage across repeated
failure marking and failures during `RECOVERING`, and refuses terminal
`COMPLETE`. Rootless direct-C coverage must prove both the state construction
and durable idempotent update under the held owner lock. These primitives are
not lifecycle commands; keep privileged actions disabled until provisioning,
mapper ownership, rollback and recovery actually use them.

The owner-claim writer must fsync the consumed record, then atomically persist
the initial `READY` state, then fsync and publish the active marker. Under the
same lock, reconciliation may close exact `READY` with either its matching
active marker or no marker, and may release an exact `COMPLETE` state with its
matching active marker. It must validate the consumed record and any active
record before atomically replacing untouched `READY` with `COMPLETE` or
releasing ownership. This metadata-only close is a reconciler-specific
operation, not a normal stage-graph edge. Do not write an intermediate
`DISABLING` stage: after a crash that stage cannot distinguish an untouched
claim from a teardown in progress. Missing or mismatched provenance, malformed
state, an active marker without state, and every other orphan stage must fail
closed. Rootless direct-C regressions must model both `READY` interruption
windows and the `COMPLETE`-before-marker-release window, prove that missing
provenance leaves the `READY` bytes unchanged, and verify fresh-run admission
only after the old state is durably `COMPLETE`. This reconciler must not touch
device, swap, module, or mapper state. A duplicate or competing owner-claim
attempt must fail while the active marker exists without changing the state,
consumed record or marker; only a caller's explicit reconciliation step may
close a metadata-only `READY` transaction.

The metadata-only `primary prepare` command and the prepared-start coordinator
remain behind the global disabled lifecycle gate until the complete coordinator
is qualified. Its production
path must reject any non-root, dirty-source, stale qualification, artifact
mismatch, recovery-filesystem failure, target identity/header drift, nonzero
selected-target swap use, duplicate or ambiguous selected-target swap aliases,
mount/root dependency, loaded module or existing mapper. Unrelated swap entries
may remain active and must never be modified by metadata preparation. It must
repeat the exact swap and block-zero checks immediately before claiming. After claim, focused rootless lifecycle tests must verify durable
consumed/`READY`/active ordering, manifest readback, optional-backup behavior,
and recovery from interruption after each metadata publication, including the
atomic `READY` close and owner-marker release. Where platform behavior is
needed, use deterministic fault injection on an owned RAM-backed `null_blk`
target; no such test may open or write a host block device. The rootless build
must keep the command unavailable and prove no host path or lifecycle side
effect is reached. After the ordinary loaded owned-null_blk smoke, the official
loaded stage must also execute one private success-cycle rehearsal with
`SWAPZ_PRIMARY_OWNED_NULLBLK_TEST`: create a uniquely owned memory-backed
null_blk disk, create exactly one real partition with a kernel PARTUUID,
initialize only that RAM partition, compile a noninstalled exact-source
`swapzctl` under a root-owned private prefix, and generate a private
parser-valid qualification record bound to the exact test binary/module/oracle
hashes and live host identity. The production coordinator must then complete
`prepare -> start -> stop` using its normal module load, Device Mapper,
`mkswap`, native `swapon` and native `swapoff` paths. The rehearsal must
prove one run ID through READY/ACTIVE/COMPLETE, the run-bound DM UUID, exact
owned-partition dependency, active swap device identity, retained consumed
provenance and LOADED module WAL, final COMPLETE state, owner-marker removal,
and byte-identical host swap-device inventory before/after. On post-start
failure cleanup must use only the manager's normal recovery command; if
recovery, mapper/module cleanup, host swap identity, or owned-device identity
cannot be proved, quarantine the RAM device and evidence instead of forcing
removal. This private credential is never an owner qualification and must never
be imported into production recovery storage. The owned-null_blk build may
also expose deterministic process-death points through
`SWAPZ_PRIMARY_TEST_INTERRUPT_AFTER`; the production build must compile every
such point to a no-op and must not read the environment. A selected test point
terminates with `_exit(86)` after the named durable milestone, deliberately
skipping in-process cleanup so a fresh `primary recover` invocation exercises
the same stale state a killed process would leave. The official owned-null_blk lifecycle rehearsal must drive all six initial
milestones: durable STARTING, module-load WAL LOADED, mapper resumed, native
swapon before ACTIVE publication, durable STOPPING, and native swapoff before
mapper removal. Each injected process must exit with the private deterministic
status, the harness must verify the expected intermediate module/mapper/swap
facts and durable STARTING or STOPPING record, and a fresh process must run the
normal recovery command. Recovery must finish COMPLETE with the interrupted
stage preserved as recovery_previous_stage, remove the active owner marker,
retain permanent consumed provenance, restore the exact pre-test host swap
inventory, and leave no swapz mapper or module. At every interrupted phase
where a mapper exists, the harness must independently prove the exact run-bound
DM UUID and exact owned-partition table dependency, not merely mapper-name
presence. It must also compare the unrelated host swap inventory while the
private mapper is active. After each successful recovery, a second fresh
recovery attempt must be safely rejected without changing the byte identity of
the durable COMPLETE record, module/mapper state, or host swap inventory; this
is the native idempotence proof for a terminal transaction.

A negative-case process must emit a stable test-only marker proving the
selected syscall, inventory or fsync boundary really fired; a nonzero process
exit and plausible kernel facts alone do not establish fault coverage. The
stale-run-ID fixture must mutate only the run-ID field of the original canonical
state record, preserving every other byte so a rejection proves transaction
ownership rather than JSON-parser strictness. For denied recovery, unchanged
kernel inventory must be accompanied by byte-identical durable owner claims
and state. Teardown must quarantine an unfinished READY transaction, a durable record
that fails byte-exact canonical COMPLETE serialization (even if a permissive
JSON decoder accepts it), a noncanonical owner claim, or an orphan owner marker even when
the module and mapper are already absent; no test cleanup may discard the last
recovery provenance. The validated source SHA must name the current checkout.

Every deterministic process-death point must snapshot its exact native
durable state, consumed owner record, active marker, manifest, and (once
published) module-load WAL in a run-and-phase-unique evidence directory before
fresh-process recovery. Evidence reads must validate regular-file ownership,
mode and link identity, and copied bytes and the evidence directory must be
fsynced. Evidence preservation failures quarantine the owned resources. Swap
inventory oracles must fail closed on a present but unstatable swap-device path,
never infer swap inactivity from a skipped entry. The loaded rehearsal also
requires a clean checkout at the exact validated HEAD, not just an earlier
build-info hash.

The same private rehearsal must exercise negative kernel-boundary cases against
the real coordinator: ambiguous `swapon` and `swapoff` outcomes both with and
without the kernel operation applied, unreadable post-operation swap inventory,
a definite failed `swapoff`, a wrong inactive mapper identity, stale run ID,
a failed durable state-directory `fsync`, and lost state provenance. A
test-only linker-wrap fixture may intercept only the private owned-null_blk
binary's `syscall`, `/proc/swaps` `open`, and `fsync` boundaries and must forward
them unchanged when no named fault is selected. That fixture is never linked by
the public Makefile, installed package, physical qualification seam, or
production authority path. Wrong-mapper testing may normally remove/recreate
only the exact private mapper after independently proving it is inactive and
has zero users; it must never force removal. State-corruption cases must first
preserve the exact durable bytes in the token-bound evidence directory, fsync
the evidence, restore those exact bytes before cleanup, and quarantine the
owned resources if restoration or normal recovery cannot be proved. Every
negative refusal must independently inspect mapper/module/swap facts and
unrelated host swap identity, then restore the controlled fixture and converge
through ordinary fresh-process recovery or retain explicit quarantine evidence.
The loaded-stage wrapper must bound the complete success, eleven native-process
interruptions and negative rehearsal without weakening per-operation timeouts or
quarantine-on-uncertain-cleanup policy. In addition to the four STARTING and two
STOPPING death points, owned-null_blk qualification must kill a fresh recovery
process immediately after durable RECOVERING, swapoff, mapper removal, module
unload and durable RESTORED. Each recovery interruption must preserve the first
STARTING origin, exact transaction ownership and unrelated host swap identity,
then converge in a new process with only the side effects still present at that
boundary. Production builds keep these interruption hooks compiled to no-ops. Rootless direct-C coverage must
also prove the native activation/deactivation helpers return `ENODEV` with
their side-effect outputs cleared. The shared production syscall/inventory transition helper must also
be exercised from direct-C rootless tests with fake inventory and syscall
adapters. Cover successful and failed `swapon`/`swapoff`, `EINTR` reconciliation,
post-operation inventory failure, already-active/inactive state, and raw-backing
swap refusal. The independent lifecycle model remains supplemental; it must not
be the only behavioral evidence for production logic. The adversarial lifecycle
audit must verify native `swapon` is ordered before durable `ACTIVE`, and native
`swapoff` is ordered before mapper removal in both stop and recovery. The
privileged execution gate remains
explicitly zero until owned-RAM interruption coverage and bounded physical
lifecycle evidence are added; source presence of the syscalls alone is not
authorization. A metadata-preparation PASS is not start, live-swap,
loaded-recovery, boot, performance, or production qualification.

The prepared-start coordinator may consume only an exact owned `READY`
transaction whose current configured target, immutable manifest, accepted owner
qualification and live artifact hashes still match. Before persisting
`STARTING`, it must revalidate mount/root/recovery topology, prove the selected
partition is not active swap, verify module/mapper absence, open the
manifest-bound PARTUUID target exclusively, and compare all 4096 current
block-zero bytes with the digest-verified saved header. Only after `STARTING`
is durable may it write the run-bound SWZ header, load the exact qualified
module, create/resume the exact run-bound mapper, initialize Linux swap metadata
on that mapper, call native `swapon` through `/proc/self/fd/N` for the already
verified mapper descriptor, and prove that `/proc/swaps` contains the exact
mapper device while the raw backing device is absent before persisting
`ACTIVE`. A successful syscall return alone is not activation proof. The primary
manager is the sole owner of swap activation; the packaged
`.swap` unit is a passive status view and must not be independently enabled or
used as a second lifecycle owner. Every failure after durable `STARTING` must
mark `RECOVERY_REQUIRED` while the owner lock is still held. Normal stop
persists `STOPPING` before deactivation and cleanup, calls native `swapoff` for
the exact verified mapper when active, and proves it absent from `/proc/swaps`
before mapper removal. It must remove only the exact manifest-bound mapper with
zero swap/open references, and unload only
a module backed by the same run's exact `LOADED` ownership record, matching
loaded source provenance and physical-backing parameter, using non-forced
`delete_module`. After cleanup it must verify the backing partition still has
the exact run-bound SWZ header, persist `RESTORED` then terminal `COMPLETE`,
and release the active owner marker. The disposable-card mission intentionally
does not restore a historical raw swap/filesystem header during normal stop;
leaving the SWZ authorization header prevents accidental raw-swap reuse. Any
failure after `STOPPING` but before `COMPLETE` must mark
`RECOVERY_REQUIRED`.

Standalone recovery accepts an exact owned `RECOVERY_REQUIRED` record or a
durable stage that may remain after an abrupt process exit once mutation could
have begun: `STARTING`, `ACTIVE`, `STOPPING`, `RECOVERING`, or
`RESTORED`. It must reject `READY`, `DISABLING`, and terminal `COMPLETE`.
For a recoverable non-`RECOVERY_REQUIRED` stage it first validates the exact
manifest and recognized block-zero bytes, then durably normalizes the state to
`RECOVERY_REQUIRED` while preserving the original interrupted stage before
entering `RECOVERING`. This covers process death before the failing coordinator
could mark recovery itself, including stale `ACTIVE` after a reboot; a live
swap mapper still cannot be removed because the mapper-removal gate refuses
active swap and open references. Recovery retains the original interrupted-stage
provenance through `RECOVERING`, `RESTORED`, and `COMPLETE`. Before cleanup
it must read block zero through
the revalidated PARTUUID path and accept only one of two byte-exact values: the
digest-verified saved original header or the run-bound SWZ authorization
header. Unknown or torn bytes stop recovery before cleanup. It then persists
`RECOVERING`, removes or proves absent only the manifest-bound inactive mapper,
and unloads a module only when live provenance matches the manifest and the
per-run module-load WAL is `LOADED` or, for the crash window around
`finit_module`, `INTENT`. A failure before INTENT may have no module-load
record; recovery may proceed only when the module is actually absent. After
cleanup it exclusively reopens the same manifest-bound target and rechecks that
block zero is still one of the same two known values before persisting
`RESTORED`/terminal `COMPLETE` and releasing the owner marker. Recovery never
restores historical raw bytes on the disposable card, never force-removes a
mapper/module, and never adopts a live module without matching WAL. Any failure
after entering `RECOVERING` must return to `RECOVERY_REQUIRED` while
preserving the original interrupted stage. Keep execution disabled until the
required interruption/null_blk/physical evidence are complete.

When the primary manager records an optional original-header backup, it is
immutable per run ID. Its writer must require the exclusive lock and matching
consumed/active owner claim,
validate the caller-bound SHA-256 before writing, create a root-owned 0600
temporary file, fsync it, atomically install the final name without replacing
an existing backup, and fsync the recovery directory. Its reader must reject
symlinks, non-regular or multiply linked files, wrong ownership/mode/size,
short or extended contents, and digest mismatch; it copies bytes to the caller
only after full validation. Rootless tests must verify exact 4096-byte
round-trip, no-overwrite behavior, invalid digest refusal, and output-buffer
preservation on read failure. If a transaction records this optional backup,
the lifecycle caller must bind its expected hash to block zero read through the
freshly revalidated descriptor for the configured PARTUUID before the first
mutation.

Any primary-swap block-zero write must use the checked descriptor primitive in
`src/userspace/swapz-primary.c`. Before writing, production callers must open
the configured target by its stable PARTUUID with `O_RDWR|O_EXCL`, then verify
the opened descriptor's major:minor, `BLKGETSIZE64` geometry and sysfs PARTUUID
against the immutable transaction manifest. Recheck the by-PARTUUID alias
before and after opening to close path-substitution races. Do not require a
content-based by-UUID link: formatting can remove it and the selected target
may not have had a swap signature. After formatting, use the same stable
PARTUUID path and manifest-bound identity. The lifecycle caller must validate
the written SWZ header and run ID against the durable manifest. Rootless path
tests must use synthetic identities and prove that no host block device is
opened.

The checked primitive independently requires an open read/write descriptor
whose device number and capacity match the selected runtime target, compares
all 4096 current bytes with the caller-bound expected header before writing,
handles short writes, calls `fsync`, then rereads and compares all 4096
replacement bytes. A stale header must fail with no write. Rootless direct-C
coverage uses only temporary regular-file fixtures to verify exact replacement
and stale-header refusal; it does not qualify kernel block-device
exclusive-open behavior or physical recovery. Keep the primitive disconnected
from privileged lifecycle commands until the full manifest binding and
recovery use are implemented and tested.

The native primary manager's immutable run manifest is separate from the
mutable lifecycle stage. Its canonical newline-delimited schema has fixed field
order and rejects duplicate or unknown fields, alternate numeric spellings,
and trailing data. It binds the run ID, 40-character lowercase qualified
source commit, `swapzctl` and module SHA-256 values, qualification-report
SHA-256, configured PARTUUID, discovered major:minor and byte size, original
block-zero digest, maximum `/8` logical capacity, generated per-run mapper
name/UUID, and exact Device Mapper table. The writer requires the held PARTUUID
lock and matching active/consumed claim, installs a root-owned 0600 file with
fsync and no-replace atomic rename, fsyncs the directory, and verifies exact
readback. The reader validates file identity and metadata, canonical contents,
and requested run ID before returning data. Rootless direct-C tests cover
round-trip, malformed fixed identity, invalid source digest, no-overwrite,
tamper refusal, and output preservation. These primitives do not validate that
the supplied hashes came from an accepted owner qualification; a trusted
qualification-evidence reader and lifecycle caller must prove that before
creating or consuming the manifest. Public format entry points must validate
NUL termination within each fixed-size field before using it in names or
formatted records; do not scan beyond a caller-provided manifest structure.

The userspace recovery code must calculate SHA-256 in process. Do not invoke a
PATH-resolved or fixed-path hashing subprocess for the original header or
qualification artifacts. Keep the implementation bounded and check padding
length overflow before processing. Native tests must include the standard
empty-input and `abc` vectors, a multi-block input with a known digest, and an
oversize-length refusal that leaves the output digest untouched.
`swapz_primary_sha256_regular_fd()` is the artifact-file boundary: callers open
the exact path with `O_NOFOLLOW`, and the primitive accepts only a read-only,
single-link, private regular file owned by the expected account. It bounds
allocation to 64 MiB, reads the full file, checks for growth, and compares
device/inode/mode/owner/size/mtime/ctime before returning a digest. Tests must
cover digest correctness, writable-FD refusal, oversized files, unsafe mode,
hard-link refusal, and output preservation. This does not establish that a
path names an accepted artifact; callers must bind the opened descriptor to
the exact expected path and qualification record.

Root builds embed the committed Git source SHA and a clean/dirty bit for the
production and packaging inputs into both `swapzctl` and `dm-swapz.ko`. The
kernel exposes the same values as read-only module parameters and ELF module
metadata. The read-only primary plan reports both identities and whether they
match; a mismatch, dirty input, missing value, or `unknown` source must remain
ineligible. DKMS packaging must copy the generated provenance header into its
owned source tree before calculating the source manifest. Build metadata is
diagnostic and must never be accepted as qualification by itself. The primary
lifecycle admission must compare these embedded values with an accepted
qualification record and independently hash the live binary artifacts before
it can be enabled. Changes to this build metadata alter the qualified module
and userspace artifacts and therefore require exact-source owner
qualification before live activation.
The generated header must be written atomically and keep its timestamp when
its contents are unchanged; repeated `make test` invocations must retain the
existing incremental-build contract.

The rootless package lifecycle regression must install a deterministic private
build-provenance header into its sandbox, compile `swapzctl` with that header,
and prove DKMS receives byte-identical provenance in its owned source tree.
The test override is valid only under the hermetic package sandbox and must
not change the production package path.
Synthetic qualification inputs in that regression must have no group/world
write bits regardless of the test process umask. The root `make` target must
normalize the exact qualified artifact modes and the official report writer
must create a non-group/world-writable report, so `make install` can admit the
same bytes without relaxing the package's safe-input checks.

Production `make install` is admission-only and must not depend on the root
`all` build target. It may consume only the already-qualified `swapzctl`,
round-trip oracle and normal module bytes. Admission requires the exact
five-stage PASS report, clean embedded source provenance, report artifact
digests, a report-only descendant checkout with no relevant dirty inputs,
current-kernel headers, and matching module vermagic. Secure Boot admission is
verification-only: packaging must never append or replace a signature after
qualification, and an enabled host with unavailable certificate/signature
verification must fail closed. Verification must parse the appended Linux
module-signature trailer and cryptographically verify the detached PKCS#7/CMS
signature over the exact module payload against the configured certificate.
Embedded CMS signer certificates must be excluded from signer resolution
(OpenSSL `-nointern`): `-certfile` alone does not force verification against
that exact configured and enrolled certificate.
Certificate identity, `mokutil --test-key` enrollment, embedded signer/key
metadata, cryptographic signature validity, and target-kernel acceptance are
separate facts. `modinfo` signer or `sig_key` metadata is diagnostic only and
must never substitute for cryptographic verification. Packaging may report
cryptographic validity plus enrollment, but it must not claim that the target
kernel accepted the module under its configured enforcement policy until the
same exact installed bytes have been safely and authoritatively loaded by that
kernel.

DKMS remains the compatibility/header integration mechanism, not the artifact
authority. After a successful current-kernel DKMS build/install, packaging must
replace the DKMS-produced module with the exact qualified module, verify its
SHA-256 before and after `depmod`, and require `modinfo -n dm_swapz` to
resolve to that exact owned path, including re-verification of an existing
installation and both install/uninstall rollback paths before activation files
can be republished. `AUTOINSTALL="no"` remains mandatory so a
kernel upgrade cannot silently carry qualification forward; a new running
kernel requires matching headers/vermagic, exact artifact qualification and an
explicit install.

Package install/upgrade must be serialized and transactional. Exact repeated
install is a verified no-op. Any non-identical upgrade must refuse while
`dm_swapz` is loaded or any swapz mapper exists, stage replacement files
before publishing them, and restore the previous verified source, userspace
files and exact installed module if DKMS, hashing, depmod, systemd reload or a
caught HUP/INT/TERM fails. Uninstall must refuse loaded-module, active-mapper,
active/enabled-unit, recovery-owner and digest/ownership mismatches; packaging
must never call swapon/swapoff, unload a module, or remove a mapper.
Uninstall must inspect systemd unit states rather than treat the `is-enabled`
exit code alone as enabled: the passive static `.swap` unit can report `static`
with exit 0. Only verified inactive and disabled/static/masked states permit
removal; unexpected states, inconsistent return codes or unavailable systemd
queries fail closed.

Uninstall is a destructive transaction rather than a sequence of best-effort
deletions. Before the first removal it must persist a private rollback snapshot
of the verified source, userspace/systemd files and exact installed module,
fsync that material, and atomically publish an independently verifiable state
manifest containing hashes of every recovery file. Activation-capable entry
points are removed before DKMS/module mutation. Every destructive transition,
including DKMS removal, source/module removal, depmod and systemd reload, has a
durable phase. Failure or a caught HUP/INT/TERM must restore the exact verified
installation; rollback restores DKMS and the exact module and completes depmod
before package entry points, with the CLI restored atomically only after the
other files and systemd cache are valid. If rollback itself cannot finish or
is interrupted, the transaction directory and hash manifest must remain, and
all later package actions must fail closed on that durable incomplete state.
The retained state must not expose an activation path before the recovered
backend is valid. If final re-verification fails after publishing the restored
CLI, rollback must revoke the CLI and activation-capable systemd artifacts
before retaining incomplete state. Legacy pre-qualification-marker packages
must meet the same installed ownership and mode requirements as current ones;
modified file metadata or foreign module paths may not be downgraded to
permissive legacy upgrade admission.

Production packaging includes Agent 9’s read-only
`swapz-primary-runtime-health` helper and matching service in the installed
binary manifest, exact ownership checks, staged unit rendering, uninstall
snapshot and upgrade rollback. The monitoring unit is installed disabled;
active/enabled instances block removal. Verified older installs lacking both
monitoring artifacts may upgrade, and a failed upgrade restores their exact
pre-monitoring file set. A foreign or half-installed monitoring payload
must not be overwritten.

Production uses the fixed `/usr/local` prefix, trusted executable paths,
root-owned installed files with fixed modes, non-symlink package directories
and single-link non-writable artifact/report inputs.

The hermetic regression must cover clean and repeated install/uninstall,
missing kernel headers, unavailable Secure Boot verification, certificate
enrollment mismatch, cryptographically invalid signature despite matching
signer metadata, an embedded foreign CMS signer certificate, vermagic mismatch,
unexpected paths/symlinks, foreign
artifacts, partial DKMS failure, active-module and active-mapper upgrade
refusal, active uninstall refusal, systemd static-unit allowance and active/enabled/
uninspectable-unit refusal, rollback of a failed upgrade, every
destructive uninstall transition, failed depmod, failed systemd daemon-reload,
reinstall after safe cleanup, installed-module/userspace digest mismatch,
post-depmod tamper, install/uninstall signal interruption, stale rollback
temporary-name collisions, legacy rollback, metadata downgrade refusal,
post-CLI re-verification failure, foreign monitoring payload refusal, foreign module resolution refusal,
monitor helper/service rollback from a pre-monitor installation, and
interruption of uninstall rollback. The
interrupted-rollback fixture must verify the retained
state manifest against the recovery bytes and prove later package operations
refuse that durable incomplete transaction without reading or modifying host
swap state. Sandbox artifacts must stay private to the package sandbox and
must not replace the repository's qualification build outputs.
The project-goals CI runs the same hermetic package fixture in an early
independent step before the combined rootless gate, so unrelated test failures
cannot mask packaging regressions. It neither replaces `make test` as the
official operator interface nor proves real-host module acceptance.
Incremental-build Makefile fixtures that compile or stage the primary manager
must include the committed fallback `src/kernel/swapz-build-info.h`; otherwise
they do not model the source inputs of the real checkout.

The primary qualification reader accepts only the root-owned
`/var/lib/swapz/physical-recovery/primary-qualification.json` report. It must
be a stable, single-link regular file with no group/world write permission and
at most 64 MiB. The C parser requires schema `swapz-test-results-v1`, matching
source and tested-commit SHAs, overall PASS, the RAM-backed qualification
scope, the same x86_64 machine-id digest, all five named stages with PASS and
exit code zero, and AVAILABLE SHA-256 values for the formatter, module and
oracle. It rejects duplicate required keys, malformed or trailing JSON, a
different source or host, and incomplete stages. This report-content check
does not replace live executable/module hashing; those hashes must be matched
before any primary lifecycle operation is enabled.

The read-only primary plan must independently hash the running `swapzctl`
through `/proc/self/exe`, the package-matched `libexec/swapz/device-roundtrip`,
and the package-held exact `libexec/swapz/dm-swapz.ko` module image. The
package must retain this image byte-for-byte from the qualified build; a
separate DKMS rebuild is not a substitute. It must compare all
three live SHA-256 values with the owner report (`formatter_sha256` is the
historical report key for `swapzctl`) and report each observed digest and
match result. Missing, unsafe, changed, or ambiguous files remain ineligible.
The module file hash proves which bytes are available for a future checked
load; source-provenance metadata alone cannot establish the bytes of a module
that was already loaded. Lifecycle admission must either prove a durable
manager-owned exact-load record for that live module or reject it. Rootless
fixtures must prove that host artifact paths are never read and that a mismatch
in any one digest fails the aggregate comparison.

The hermetic DKMS package test supplies a synthetic module artifact only from
inside its private sandbox through `SWAPZ_TEST_MODULE_ARTIFACT`. That test hook
must be rejected outside the sandbox and must not change the production module
source path. Package ownership hashes and uninstall checks must cover the
retained module image as well as the CLI, oracle and systemd files.

`swapzctl primary qualification-import <report>` is an explicit root-only
metadata operation. It accepts only a stable, non-writable regular input
report that matches the running build source, this x86_64 host identity, all
five passing stages and the live three-artifact hashes. It requires the
validated persistent recovery directory, the partition lock, no active owner
marker and no unfinished primary state. It durably stores the exact report
bytes at the fixed path; a replaced report is preserved under a SHA-256 name.
This command does not prepare the partition, load the module, create a mapper
or enable swap. Rootless tests must exercise atomic store, repeat store,
prior-report preservation and refusal while an active marker exists.

Primary module admission opens `libexec/swapz/dm-swapz.ko` relative to the
installed control executable using descriptor-relative traversal. Focused
rootless tests must accept the exact stable read-only file and reject a
digest mismatch, a writable file, a hard link, a symlinked module, a
symlinked parent directory and an executable path containing traversal
components. The validated descriptor is the object that the later
`finit_module()` caller must use; tests must not load a host module.
The read-only plan and qualification import must use this opener with the
owner-report module digest; a failed path or digest check keeps the artifact
gate false.
The checked loader must repeat the current report and three-artifact checks,
refuse any preloaded module or swapz mapper, use the returned module FD for
`finit_module()` with the physical-backing opt-in, and verify the loaded
source and parameter. Before the loader runs, the STARTING coordinator must
durably create a no-replace per-run module-load record binding run ID, source,
qualified module SHA-256 and qualification-report SHA-256 with phase `INTENT`.
After successful loader verification it atomically replaces only that exact
record with phase `LOADED` and verifies readback. A crash may therefore leave
either an INTENT record with no module, or an INTENT/LOADED record that recovery
must reconcile against live module state; absence of the record never permits
adopting a preloaded module. Rootless direct-C tests must exercise exact
INTENT-to-LOADED persistence, duplicate-intent refusal and phase mismatch.
They must also verify strict module-boolean parsing and that the load command
returns `ENODEV` without changing its ownership result or touching host paths.

The primary manager's Device Mapper layer must keep privileged create/remove
calls disabled until the whole coordinator is qualified. Rootless production-C
tests must exercise the manifest-derived maximum table, exact stable
`swapz-primary` name, run-bound UUID, ioctl buffer alignment, one-target bounds, exact `swapz` parameters,
and rejection of altered lengths, target counts, versions, UUIDs, padding and
unaligned payloads. The rootless build must prove that mapper create/remove
return `ENODEV` without setting any side-effect result. A strict production
userspace compile must also compile the guarded ioctl implementation. These
checks do not emulate kernel Device Mapper behavior or authorize a mapper on
the host.

The shared transaction-to-manifest admission check must require the matching
owner claim, allowed durable stage and exact stored manifest. If a transaction
records an original 4096-byte block-zero backup, admission must verify its
digest before using it; a backup is optional for the disposable development
card and must not become a lifecycle gate. Rootless direct-C coverage must
exercise a transaction with no backup, accept arbitrary saved block-zero bytes
when a backup is present, and refuse a digest-tampered backup or disallowed
stage before mapper lifecycle operations are admitted. The header-signature
predicate may identify a Linux swap header but must not require one or treat
an SWZ header as one. The production digest is bound per transaction in the
manifest. These tests do not perform or authorize block I/O.

Before future lifecycle enablement, interruption points after device creation,
inactive-table load, resume and during cleanup must be covered by rootless
state-machine/direct-C tests and deterministic fault injection against an owned
RAM-backed `null_blk` target. The lifecycle must then pass safely bounded
physical-host recovery and swap checks on the positively identified authorized
card before it is enabled by default. VM coverage is not required. Do not
intentionally crash or reboot the host to create interruption evidence.
Recovery may remove only the exact manifest-bound mapper, an exact active
table or exact suspended inactive table, zero open references and an inactive
swap mapping. It must prove both name and UUID absent after non-forced removal.
Missing, substituted, extra-target, extra-dependency or unqueryable mapper
state remains a recovery stop condition; rootless parser coverage alone cannot
close the loaded or physical-host gates.

The primary manager's transaction-ID generator must use the operating system's
cryptographic random source, handle interrupted and partial reads, return only
lowercase 32-hex IDs, and leave its output unchanged on failure. Rootless
direct-C coverage must validate generated IDs and exercise deterministic
header construction from a known ID for multiple synthetic target geometries.
The 4096-byte candidate must pass the shared SWZ validator for the supplied
device capacity, contain the exact
16-byte ID, and have zero reserved bytes. Malformed and all-zero IDs must be
rejected without altering the caller's header buffer. These tests establish
format construction only; they do not authorize writes or close loaded
recovery, physical-swap, or production-acceptance gates.

## Qualification discovery and release-evidence integrity

Lifecycle execution-gate assertions must evaluate the active C preprocessor
configuration rather than the first textual `#define`. Ordinary production
must resolve `SWAPZ_PRIMARY_EXECUTION_ENABLED` to 0; owned-null_blk and
physical qualification may resolve it to 1 only with all private controls
present, and the two private modes must fail when combined. The read-only
primary plan and mutating command dispatcher must use the same derived
compile-time-plus-runtime gate. `privileged_execution_enabled` must therefore
report false for the ordinary build, true for owned-null_blk qualification, and
true for physical qualification only while its explicit runtime marker is
exactly enabled. A truthful true value in a private qualification binary is
evidence about that test seam only: it does not authorize or enable ordinary
production lifecycle execution. Ordinary preprocessed source must not read the
physical runtime marker. Comments and string literals containing fake gate or
syscall text never satisfy safety assertions.

The official rootless stage directly executes every mandatory Python contract
owned by that stage, including the owned-null_blk lifecycle qualifier and
`primary-real-swap-test.py`; the latter remains unit-only in GitHub Actions
and its privileged helper must block there. The source contract keeps an
explicit direct-suite registry and requires each path to exist and appear
exactly once in `test-rootless.sh`. The analyzer contract remains mandatory
through `tests -> suites test-all -> test-predictor -> test-anon-page-analyzer`
and is checked without duplicating its execution. Project-goal CI separately
pins the source-contract invocation and these discovery paths so removal or
renaming cannot silently reduce qualification coverage. `make test` remains
the sole qualification interface; `make fast_test` remains development-only.

`docs/handoff/production-readiness.json` is observational release evidence,
not a qualification result. Every current PASS must bind to the exact
production source and carry the evidence appropriate to its gate: clean build
state, qualified formatter/module/oracle hashes, both required CI runs,
exact-source owner `make test`, owned-null_blk lifecycle qualification, real
Linux swap-out/in, maximum-capacity plus measured RAM evidence, sustained
physical performance, lifecycle/deployment state, installed artifact identity,
armed cold-boot harness, and owner-observed reboot. Missing, historical, stale,
source-unbound, or structurally incomplete observations are BLOCKED or
IN_PROGRESS, never PASS; a current FAIL stays FAIL. The owner `make test`
evidence must carry the same formatter/module/oracle digests as the qualified
artifact evidence. Real-swap PASS evidence must carry the installed qualified
formatter/module/oracle digests observed by the physical helper, and those
digests plus installed artifact identity must match the exact qualified release
artifacts. Real-swap, maximum-capacity/RAM and sustained-physical PASS evidence
must bind the SHA-256 of the exact current `FROZEN`
`docs/production-acceptance.json`; changing that policy invalidates those
physical PASS observations until they are requalified. Release evaluation must
parse that policy with duplicate-key rejection, require exactly the canonical
top-level fields and expected physical-contract schema, and BLOCK rather than
hash a malformed merely-`FROZEN` document. The physical real-swap
helper and physical-performance summary must emit that exact policy digest in
their own result/evidence payloads so release aggregation never reconstructs or
guesses the policy binding after the run. Release-evidence unit fixtures must
use independent artifact-hash mappings for qualified, owner-report and
installed records; mutating one record must never mutate another and hide a
cross-binding mismatch. Current release evidence must also include one canonical
authorized-target identity consisting of the normalized lowercase PARTUUID and
exact partition byte size. Real-swap, maximum-capacity/RAM, sustained-physical,
lifecycle/deployment, armed cold-boot and owner-observed reboot PASS records
must bind that same tuple. Runtime major:minor is deliberately excluded because
it may change across attachment or boot; this is a consistency check and does
not claim PARTUUID plus size is cryptographic or physical-card uniqueness. A
retained old host snapshot must be labeled HISTORICAL and cannot become a
current release verdict.
Code/deployment readiness-for-owner-reboot is reported separately from the
owner-observed cold-boot result so automation never fabricates reboot evidence.

The private `tests/tools/evaluate-production-readiness.py` evaluator is the
executable form of this release-evidence contract; it is not a new operator
command and never performs privileged work. It must derive readiness rather
than trust summary PASS fields. It strictly rejects duplicate JSON keys,
requires a FROZEN canonical production-acceptance policy, hashes the exact
policy bytes, binds owner `make test`, all three required CI workflows
(`Native kernel-C project-goal regressions`,
`Experimental swapz production C qualification`, and
`Systemd and package production-readiness`) and all qualified artifacts to one
exact synchronized `main` SHA, and independently
cross-checks formatter/module/oracle hashes. Current PASS physical records bind
the normalized lowercase PARTUUID plus exact partition byte size and the frozen
policy SHA-256. Full-capacity evidence must include measured positive logical
capacity and measured peak target/metadata RAM no greater than the frozen
`metadata_and_target_peak_ram_bytes_max`. Current code readiness also requires
zero explicitly recorded unresolved critical correctness/ownership/race issues.
Deployment readiness additionally requires lifecycle/deployment PASS, exact
installed artifact hashes and an armed cold-boot harness. Owner reboot
observation remains a separate PASS/FAIL/NO field and can never be inferred
from code or deployment readiness. Unit fixtures must prove stale source,
historical evidence, owner-test failure, CI mismatch, artifact mismatch, target
mismatch, policy mismatch, over-budget RAM, unresolved critical issues and
unarmed deployment all fail closed.

Source-contract assertions follow the component that owns a safety transition.
For FUA, the contract requires the lower flush before any successful upper BIO
completion and requires unsafe flush errors to fail the target even when the GC
path has a separately recoverable pre-publication case. For GC role rotation,
the Device Mapper contract verifies begin/commit ordering and recovery-token
binding, while direct `gc_allocation`, forbidden-segment and role-reset
assertions are made against the authority begin/commit helpers that exclusively
own those fields. Tests must not require obsolete direct field writes in a
caller after ownership has moved behind those helpers.
Mandatory Python qualification suites must remain syntactically valid; a path that exists but cannot execute does not satisfy discovery coverage.


### Runtime systemd health and non-hibernation regression

The isolated systemd fixture must exercise the runtime-health helper and unit
without reading or changing host swap state. Cover exact mapper/run/backing
identity, foreign mapper rejection, active swap inventory and capacity,
configured backing-path disappearance as a hard failure, monitoring-command
failure as degraded evidence, low-noise unchanged polling, kernel/systemd
telemetry, and sustained GC pressure without progress. Target
health failures must remain observable rather than causing the monitor service
to restart the primary lifecycle; only monitor-process failure is eligible for
`Restart=on-failure`.

Rootless transactions must retain missing-media no-swap behavior, interrupted
startup, failed native stop, and service-restart contracts. A failed stop must
execute the native `primary stop` once; any `ExecStopPost` observer is
read-only, ignored for unit-result ownership, and may not force removal or
recreate/reformat a mapping that could still contain live pages.

Test hibernation exclusion with literal mapper paths, selected PARTUUID/device
aliases, tagged UUID aliases, initramfs `RESUME=auto`, sysfs resume identity,
and active mapper inventory. The generator must emit guards for
`systemd-hibernate.service`, `systemd-hybrid-sleep.service`, and
`systemd-suspend-then-hibernate.service` even when selector-derived mapper
drop-ins cannot be emitted. Its manager-failure regression must make the mocked
`swapzctl primary systemd-units` command actually return nonzero; setting an
unused fixture variable is not failure coverage. Cold-boot PASS remains exclusively the
owner-triggered cross-boot verifier; rootless fixtures and daemon-reload checks
cannot manufacture observed cold-boot evidence.


### Primary runtime observer audit regressions

Rootless systemd tests must use authentic tab-delimited `/proc/swaps`
entries, including long absolute paths, to assert actual used/remaining
capacity rather than accepting a zero-usage false positive. Empty, truncated,
malformed, or unreadable inventories must not satisfy a hibernation guard.
A correctly formed empty inventory may allow unrelated hibernation only when
no primary target is configured, no swapz mapper is active, and kernel/initramfs
resume evidence is safe. A configured primary target must block hibernation for
the whole configured interval, and mapper activation must independently refuse
to begin while a hibernation-capable systemd unit is active or activating.
Exercise missing removable media plus unresolved `/dev` and tagged resume
aliases; admit only a provably distinct stable identity. Missing
`/proc/cmdline` and a live mapper whose target authority cannot be
resolved both require fail-closed results. Assert bounded journal observation,
finite deadlines for external observer commands, a fixed production PATH, and
portable mixed-case kernel error detection. These tests remain rootless and
must never perform host swap or hibernation actions.

 
Raw triple-quoted shell fixtures preserve the literal backslash preceding a
newline and may lose their executable shebang after naïve dedenting. Normalize
the fixture before `chmod +x`, and exercise a real subprocess launch with
an asserted `#!/bin/sh` prefix; a registered or syntactically valid Python
fixture that cannot execute is not passing systemd coverage.

A dedicated fast CI gate must run the hermetic package transaction suite and
the rootless systemd/runtime-health suite independently of the broader product
qualification workflow. This gate is release evidence for packaging and
service contracts only; it does not replace loaded-kernel, physical-media, or
owner-observed cold-boot qualification.

Nested `make test` fixtures must track every mandatory loaded-correctness marker byte-for-byte when the parser contract grows; adding a new fail-closed recovery case requires updating the isolated fixture rather than weakening or making the marker optional.

Boot-verifier rootless fixtures must provide an explicit benign synthetic
`/proc/cmdline`; absence is reserved for the dedicated fail-closed regression.
Resume-tag tests must normalize the complete tag key as well as hexadecimal
payload characters so uppercase `PARTUUID=` syntax cannot bypass stable-identity
comparison.
