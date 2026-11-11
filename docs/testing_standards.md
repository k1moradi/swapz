# Testing Standards

## Automatic abandoned benchmark resource recovery

The benchmark producer records a separate root-only creation proof before
replay, while its successful device/mapper/module creation flags are live.
Bind the boot, creator PID/start time, source, pinned session identity, original
swap inventory (excluding volatile Used), exact RAM configfs and block-object
identities, mapper UUID/table/dependencies, and the module this session loaded.
This proof grants cleanup authority only; it is never a qualification PASS.
Legacy PID/source-only records must not acquire authority retroactively.

The existing make-test memory-preflight cleanup first recovers abandoned
sessions with complete verified proofs. Skip live creators; reject reused PIDs,
changed boot/identity, malformed or linked records, foreign holders, mounts,
active swap, open process references and busy mappers. Serialize recoverers and
revalidate adjacent to every nonforce mutation. Remove only the owned mapper
and RAM devices, then unload only that session's unchanged module when unused.
Never infer process ownership from fuser output or signal inferred holders.
Partial cleanup must remain safely retryable from the original creation proof.

Normal teardown removes its unchanged proof only after releasing all owned
resources. Recovery retains failed-run logs and never manufactures completion
or PASS markers. The existing descriptor-pinned scratch deletion and retention
rules remain separate: failed, incomplete, uncertain or quarantined evidence
stays protected. Focused tests must cover legacy refusal, active/PID-reused
creators, substitution, foreign users, interrupted poweroff, retry, and private
record symlink/hardlink/mode/content changes. Loaded qualification must also
exercise real producer registration, ordinary teardown and abandoned recovery
on newly created owned RAM devices, with native swap identity unchanged.

**Immutable naming policy (read before every prompt):** The project is `swapz`; the kernel module is `dm-swapz.ko` (loaded as `dm_swapz`); the Device Mapper target is exactly `swapz`; and the module alias is `dm-swapz`. Never put implementation-generation numbers in product, module, target, source-path, report, workflow, helper, or schema names. `SWAPSPACE2` is the only physical backing partition format. `SWZ` names the internal 4/8/16KiB extent-packing design; production extents contain only payload and zero padding, with all descriptors in RAM. Legacy serialized codecs are isolated test fixtures, **not** a partition format or permission to persist swapz metadata. Do not invent a new format identity.

**Three-tier test policy:** `make fast_test` is development-only and never qualifies or publishes `test_results.json`; `make test` runs the algorithm/RAM path and returns INCOMPLETE (nonzero) until physical source/run/target admission is qualified; `make test_full` retains all rootless DKMS/systemd integration and RAM qualification. Both privileged tiers report BLOCKED (nonzero) if noninteractive privilege is unavailable. RAM/integration PASS cannot certify physical storage or cold-boot production acceptance. Private scripts and CI jobs are implementation details, not operator interfaces.

## Official test main synchronization

`make test` and `make test_full` serialize within one checkout using a private
lock in its Git directory. Before any qualification stage, the runner requires
the canonical `main` checkout, a clean tracked source/index, and exactly one
canonical fetch and push URL for `k1moradi/swapz`. It performs a bounded,
noninteractive fetch and advances local `main` only with a checked
fast-forward. A local-only commit, divergence, remote-path collision with an
untracked file, ambiguous remote, failed fetch, or changed tracked source
blocks all stages; the runner never resets source, checks out another branch,
pushes source commits, or runs tests against a dirty checkout.

The generated `test_results.json` is the only tracked-path exception. Before
replacing a dirty copy, the runner preserves its staged and working bytes in a
mode-0700 directory under `.git`, with mode-0600 files and durable directory
entries, then restores only that report path. Other unpublished edits remain
untouched. If the pretest fast-forward changes the non-report source identity,
the runner restarts the same Make goal once so the root Makefile and runner are
both parsed from the synchronized source. It carries the lock and GNU Make
jobserver descriptors through that restart. A second source advance blocks
before the first stage; report-only commits do not cause a restart.

The runner rechecks the tested HEAD, source identity and tracked-source
cleanliness before and after each stage. Source drift stops later stages and
cannot be reported as a qualified run. After report publication, a second
bounded fetch may fast-forward local `main` if the remote is a descendant and
no local source or untracked-path conflict exists. It preserves a dirty test
report before replacing it. Local-ahead/diverged state, failed authentication,
or uncertain ancestry remains visible as a synchronization failure; existing
report publication may publish only its report-only commit. These checks keep
local and remote refs aligned when a safe fast-forward is possible without
overwriting concurrent source work.

Rootless regressions must exercise an unchanged checkout, source and
report-only advances, staged and unstaged report preservation, dirty-source
refusal, local-ahead and divergent histories, untracked collisions, failed
fetch redaction, lock contention, source re-execution, jobserver-FD transfer,
and post-test reconciliation using private local bare remotes. They must never
contact or mutate the canonical GitHub repository.

Make-interface tests that execute the official runner in a synthetic checkout
must include a tracked `test_results.json` and an isolated local bare `origin`.
If that checkout needs the canonical-origin guard, its test-only Git shim may
report the canonical URL for origin inspection while leaving fetch and push
operations connected to the local bare remote. Do not disable the production
sync guard or let the fixture contact GitHub. Synthetic loaded evidence must
bind to the newest non-report source commit, since a successful prior fixture
invocation may publish a report-only commit before the next incremental run.

## Boot-verifier fixture storage

Rootless boot-verifier fixtures must model their synthetic persistent report
directory independently of the host's temporary filesystem. Override only the
exact report-directory filesystem-type query, retain real permission and
ownership checks, and prove that both tmpfs and ramfs prevent arming. Keep the
temporary fixture self-cleaning; do not relax production persistence checks.

## Real-partition architecture preflight

The owner-approved partition architectures are little-endian x86_64 and ARM64
with 4096-byte kernel pages. Execute the actual kernel architecture gate in
native controls for x86_64, ARM64, big-endian ARM64 and unsupported/unknown
configurations; only the two supported little-endian controls may pass.
The unprivileged selector and privileged probe must reject unknown architectures
before device admission or swap drain. Pending same-boot cleanup remains
available before the selector refuses a new trial. Production report parsing
must accept ARM64 only with unchanged exact expected host/source/artifact
binding, reject an OS-only/foreign host digest, and reject unknown ISA names.
The production running-kernel and hardware-identity checks use the native
architecture while retaining kernel-release and trusted DMI UUID plus machine-id
binding. Private ARM64 null_blk machine identity must not become production
authority. VM development evidence remains explicitly virtual-only and cannot
qualify physical media. Architecture approval alone grants no partition
ownership, loaded-RAM token, physical acceptance or default-swap readiness.

## Post-PASS keep-active same-boot ownership

After the real-swap oracle passes, the interactive development trial must ask
whether to keep swapz active or return to ordinary swap. The **oracle workload**
remains deliberately bounded, but the mapper itself must use the full logical
capacity admitted by the unchanged SWAPSPACE2 header, clean 1MiB backing
segments and the production GC/COW reserve formula. Never use a fixed small test
mapper as the post-PASS service device. Before honoring a keep request,
revalidate the unchanged SWAPSPACE2 header, inactive raw partition, exact mapper
name/UUID/table/lower device, mapper Linux-swap size/priority, and loaded owned
module. The helper records `KEPT_ACTIVE` only in root-owned `/run` state and
retains the exact active partition marker.

A later cleanup process may inherit module ownership only while that exact
verified mapper still exists: the live Device Mapper target pins the
`dm_swapz` module reference, preventing unload/reload behind the mapper. It
must verify the mapper again before swapoff/removal and may then unload the
module and reactivate the original ordinary swap. If the mapper continuity is
missing or substituted, cleanup fails closed and must not unload an unproven
module. Reboot removes the volatile ownership record and kernel mapper state;
no swapz metadata or recovery image is written to the backing partition.

The direct-C qualification-report store fixture must pass separate lifecycle
and evidence directory descriptors. Verify replacement and archival in the
evidence directory, absence of report files in lifecycle state, and refusal
while the lifecycle directory contains an active ownership marker. Native lifecycle filesystem policy must admit
production tmpfs state and reject block-backed filesystems, ramfs and overlay.
The shared Linux swap header validator's two-page format minimum must agree
in kernel and userspace fixtures. Format parsing does not waive the separate
three-physical-segment target capacity gate.
The standalone swap-header parser fixture must use its local segment-page
geometry consistently in both inputs and expected layouts; it must compile
without the authority allocator's private segment constants.
Each independent header mutation must start from a fresh valid header; the
optional-UUID positive case must not inherit an invalid bad-page list.
Physical-admission source coverage must require both Linux swap layout parsing
and checked clean-segment configuration, including declared-area and bad-page
handling; the retired contiguous-only validator is not the admission API.
The geometry-only primary capacity helper is synthetic-fixture support only;
production userspace builds must compile without it and use header-derived
clean segments. Only rootless native policy fixtures retain its explicit
test-build scope; owned-nullblk manifests bind header-derived geometry.
Do not suppress unused-function warnings.
Production-only runtime-parent inspection must likewise be omitted when its
preflight caller is replaced by the rootless or owned-nullblk test seam.
Swap-inventory fixtures must provide the selected swap area's explicit size
to the current production `swapz_primary_original_swap_policy_admissible`
check, retaining filesystem-device alias rejection for unrelated versus
selected-filesystem swapfiles. The retired
`swapz_primary_original_swap_is_quiescent` symbol must not be called by
native production-inclusion fixtures: an active selected swap may have Used>0,
and START, not PREPARE, owns the swapoff migration boundary.
The rootless primary null_blk lifecycle qualifier must bind the four
pre-claim runtime-state safety, filesystem, scope, and source-chain refusal
phases to their current `runtime-state-*` names, and preserve pre-claim
`EPERM` checks. Its three raw-swap inventory gate probes must assert the
current admissibility helper, not the retired quiescence API.
The lifecycle audit must require all three PREPARE raw-swap inventory checks
to use the unchanged header's declared swap size, computed before the first
check, rather than a retired argument-free geometry assumption.
In native `test-userspace` Make recipes, shell exit-code capture and later
diagnostics must escape dollar signs as `$?` and `$script_exit_status`.
A regression must check both the captured status and its later shell
expansion so Make cannot substitute its own automatic `$?` prerequisite list
or strip shell variables, masking the original failed late-race script and
its exit code. Keep explanatory Makefile comments outside continued shell
recipe blocks to preserve the `else`/`fi` command structure.

The allocation/free source inventory must separately enumerate the sparse
backing-segment map allocated by the Linux swap layout helper, in addition to
direct constructor allocations. Its single `kvcalloc` site must match one
`kvfree` in teardown and remain included in geometry-scaled RAM accounting.
The exact 17 capacity-index allocation sites use `kvmalloc_array` for the 15
authority-initialized arrays and `kvcalloc` for only
`gc_segment_evictions` and `segment_trimmed`. Keep the separate tests
proving initialization before use, allocation count, ownership and frees;
the optimization deliberately avoids redundant memory zeroing.
Shared-root source contracts must require topology validation before exposing
the scope fingerprint and fingerprint availability before reading the owner's
scope record. Volatile lifecycle state has no recovery-disk separation phase;
do not require retired persistent-recovery markers in prepare or plan. Its
PARTUUID-derived active-marker name must reject `snprintf()` truncation from
the formatter return value; a `strlen()` check of the terminated destination
must not substitute for that bound.
Extracted owned-nullblk lifecycle fixtures must bind `RUNTIME_STATE_BASE` to
their private state tree, use the `start-header-verified` interruption phase,
and inspect the runtime filesystem helper. Stale ownership must still retain
quarantine and forbid power-off/removal; evidence-directory bindings cannot
substitute for the runtime state being checked.
The parser-only translation-unit fixture must also compile with fatal
implicit-declaration warnings: manifest priority parsing shares the production
priority helper and needs its declaration before the manifest parser.
The external-start-gate permission negative control must explicitly set its
nonprivate directory to mode 0755 after creation. An inherited restrictive
umask must not convert that negative fixture into an admitted private gate
that waits for an intentionally absent start file.

The isolated Make-interface loaded fixture must model the immutable backing
header by reporting `start-header-verified`, never the retired
`start-header-written` phase. Its documentation/source contract must reject
optional raw-partition header backups; neither synthetic recovery fixtures nor
real lifecycle paths may write the original swap header.

The standalone SWAPSPACE2 native header test must compare smaller-area
geometry against its own 256-page segment constant, without importing the
kernel allocator header. Its comments and assertions must describe smaller
declared areas and bad-page lists as supported inputs to the production
clean-segment translation, not as deferred or conservatively unsupported
physical-layout work. Linux v1 permits duplicate bad-page entries: parse
them without rewriting the header, preserve the listed entry count, and count
each contaminated clean-allocation segment only once. Reject a listed bad-page
count greater than the header-declared data-page count, even when all entries
repeat the same valid page: the declared usable swap count must never underflow.
The narrow no-bad-pages validation helper must still reject such a layout.
Restore a fresh valid swap header after the duplicate-list case so the cleared-UUID acceptance test
independently verifies optional UUID behavior.

### Failed compressed read must never publish caller bytes

The native payload-only mapping regression must distinguish malformed RAM
geometry (zero length: `-ESTALE`, no lower read) from a forged but in-bounds
length (CRC mismatch: `-EBADMSG`, bounded lower read). Both errors reset the
reported payload length to zero and leave every caller output byte unchanged.
Restoring the original authoritative length must still yield byte-exact
readback. A matching forged observed/current RAM map must additionally
reject a start block at physical capacity, a multi-block extent past the
physical end, and a four-block extent crossing a 256-block segment boundary.
Each negative must return -EUCLEAN and clear the payload pointer before
CRC, with the original map restored after the probe. Never turn an
in-bounds CRC mismatch into an imaginary pre-I/O geometry rejection or
infer physical qualification from this native test.

### Sparse Linux swap layout allocation ownership

Constructor accounting must distinguish its 47 direct heap/vmalloc allocation
sites from the conditional `segment_backing_pages` allocation inside
`swapz_configure_linux_swap_layout`. The target destructor owns and frees
all 48 possible pointers, including a partially populated sparse map on
a constructor error. The sparse temporary bitmap has independent
`bitmap_zalloc`/`bitmap_free` ownership in that helper. Keep the 47-site
constructor inventory strict; enforce the conditional allocation and both
paired frees independently, including the explicit RAM budget. Neither
ignoring the free nor silently weakening the constructor audit is acceptable.

### Rootless primary-start transition contract

The source-extracted late-race fixture must supply exactly one original-swap
transition adapter without issuing host `swapoff`, `swapon`, `mkswap`, or
raw-partition writes. Most cases model an already-inactive ordinary swap
partition; one positive control must instead bind
`original_swap_active=1` with an automatic negative Linux priority, simulate
exactly one successful deactivation, and continue through mapper activation.
That active ordinary-swap control is not an error case: START is required to
disable normal swap when needed. The positive control must include nonzero
`Used` pages so qualification proves PREPARE does not require an artificially
empty partition and that deactivation, not a pre-swapoff zero-used gate, owns
the migration boundary. An early selector/mount/target denial after
STARTING may leave the transition count at zero. A successful module/mapper
activation requires the transition to have run exactly once. Refusals after
that transition must expect `swap=OBSERVED`; refusals before it must retain
`swap=UNOBSERVED`. The actual syscall/reconciliation ownership path remains
independently tested.

## New P0 ordinary swap and RAM-metadata acceptance gate

The packed-placement fixture with lengths 2000/2073/2073/2000 must require
two one-block payload extents, two authoritative references per extent,
byte-exact readback and one two-block lower submission with no internal holes.
Serialized-descriptor overhead must not inflate this RAM-only geometry.

The exact packing planner must retain one cached `payload_start` cursor,
using it both to check remaining extent capacity and to position accepted
payloads. Its source contract rejects redundant per-candidate `remaining`
state, preserving single-update hot-loop geometry without changing 4/8/16KiB
packing or the read-cost policy.

Native compressed READ tests must prove that an undersized output buffer
returns -ENOSPC before lower I/O, without modifying caller data, even when
lower READ injection would fail. An adequately sized retry must still read
and CRC-validate the authoritative RAM-mapped payload.

For a fully completed batched lower WRITE, replay-failure fault injection must
modify a *RAM-described compressed payload byte* in the unpublished staging
image after lower completion, not extent byte zero (now deterministic padding).
The payload CRC must reject the tail with `-EBADMSG` while retaining earlier
published mappings and the exact committed-prefix count. No serialized
on-media metadata can be consulted to manufacture a descriptor-integrity
failure. GC relocation and foreground replay both exercise this path.

Real device/VM backing must already be SWAPSPACE2. Assert byte-exact backing
first-page preservation, no raw-partition mkswap, no SWAPZ001 publication,
and no raw-header write on every successful or failed path. Only the virtual
mapper may receive mkswap. The public raw-device format operation does not exist; any legacy
`swapzctl format` invocation must be rejected before a raw-device open.
Deleted formatter-success fixtures must not be recreated as acceptance tests.
The primary-manager source contract must additionally prove that its exclusive
raw-target identity/header descriptor is `O_RDONLY | O_EXCL`, never `O_RDWR`
or `O_WRONLY`; userspace raw-write capability is not an ownership primitive.
The rootless primary-policy opener fixture must likewise use `O_RDONLY | O_EXCL`
for an exclusive raw-target identity claim and `O_RDONLY` for observation,
reject `O_RDWR | O_EXCL` with `EINVAL`, and run mismatch/alias tests with
allowed read-only flags so flag validation cannot mask an identity failure.
A NULL required alias-path negative control must also pass a valid read-only
flag, demonstrating that the missing path—not flag rejection—causes `EINVAL`.
Production-extracted late-race C fixtures must also simulate the raw-target
exclusive claim with `O_RDONLY | O_EXCL` (including alias-race controls), not
an obsolete writable mode. This keeps the fixture's race assertion reachable
without weakening the raw-device read-only policy.

Source contracts for the single-block READ policy must follow the cached
`single_block_read_mode` decision through successful lower reads and cache
residency publication; production must still prevent raw lower bytes from
becoming reusable cache entries in that mode. Primary lifecycle source audits
must count the three `swapz_primary_original_swap_policy_admissible()` checks
in PREPARE, rather than a removed quiescence helper.

A 20-byte authoritative RAM logical map (including compressed CRC32C)
replaces the prior 16-byte map and increases the dedicated-card source
index estimate. The source-contract RAM accounting oracle must derive map
size from the C static assertion and keep its checked concrete reference
values synchronized; those estimates are not observed peak RAM.

The production-C RAM authority regression must also forge a matching
out-of-extent compressed payload descriptor and prove `-EUCLEAN`
before CRC reads the caller-owned image; stale and corrupted-CRC paths
remain independently checked. The shared direct/cached lower READ-range
preflight must reject compressed RAM map lengths over
`SWAPZ_MAX_COMPRESSED` even when the malformed payload still fits within
the selected extent (e.g. a 4096-byte record at offset zero in a 4096-byte
extent); do not submit speculative lower I/O for invalid maps.

The coalesced READ-chain preflight must validate each complete extent against
physical capacity, segment boundaries and legal 4/8/16KiB classes before
submitting any lower callback. It must also reject overlap between combined
lower READ scratch and any private 16KiB read buffer, or between two private
read buffers; neither alias form may reach memcpy or lower I/O. Negative
native tests must observe zero lower requests for invalid inputs.

Compressed engine reads must reject a caller payload buffer smaller than the
RAM-authoritative record length with `-ENOSPC` before read-cache probes,
lower READ submissions or CRC validation. Native regression must verify zero
lower requests, unchanged output and a successful exact-size retry.

Under an explicit one-block cold-read budget, native packed-read regressions
must verify one lower payload-block read per logical request, no inherited
hits from the legacy metadata-named payload-block cache, and byte-exact
CRC-validated readback after
overwrite and mutation fences. A separate zero/unlimited-budget scenario
covers legitimate extent and block-zero data reuse.

New source/native/loaded qualification must prove in-RAM CRC/generation,
record offsets/lengths, 4/8/16KiB packing, read correctness, GC, overwrite,
DISCARD and concurrency, partial/failing I/O, memory capacity and no stale
mapping after target recreation. Source contracts for the migrated engine must reject regressions back to
serialized descriptor lookup on compressed reads and require data-only writer
transactions to bind RAM descriptors before publication. Legacy codec helpers
may remain directly unit-tested but are not production read/write authority.
Native data-only builder coverage must also
alias its descriptor array deliberately with the lower-write image and prove
the constructor rejects that ownership violation without changing the image.
Also reject builders inside either buffer and payload inputs overlapping
the descriptor array, before any mutation. Exercise exclusive swapoff and return to
ordinary swapon without reboot; after success ask owner keep/restore.
Rootless post-PASS keep-choice tests must refuse a changed backing header,
reactivated raw swap, substituted mapper, incorrect mapper priority,
missing or unowned module, and missing active mapper. A positive fixture
must verify both raw and mapper swap-device identities; none of these
fixtures establish live-host physical qualification.
Existing raw-header preservation alone is insufficient for production PASS.
New trial selectors use `/dev/disk/by-partuuid/<PARTUUID>`, not the
filesystem UUID. An ordinary Linux swap partition may legitimately have a
cleared swap UUID; the original `SWAPSPACE2` signature, stable partition
identity, full geometry, parent and exclusive ownership must still verify.
Historical by-UUID selectors in authenticated recovery journals remain
accepted for the original transaction only. New selector support does not
bypass the loaded RAM-metadata qualification gate.
The 16 GiB native capacity fixture must account for the expanded 20-byte
volatile mapping record and current per-segment indexes: expected
index bytes are 121739228, not the historical 16-byte-map total. Count
all allocated sidecars and page-rounded memory separately.
A source contract must also verify Device Mapper `iterate_devices` excludes the
protected first page and unused tail for contiguous physical backing while
retaining zero-based null_blk. With Linux bad-page holes, the dependency span
may conservatively cover the declared data area; actual READ/WRITE/DISCARD must
still translate only through the RAM clean-segment map and never touch a bad
segment. Native userspace policy coverage must verify raw `/proc/swaps` Size
comes from the immutable Linux swap layout (`last_page - bad_pages`) and is
unchanged by 1..4095 trailing device bytes outside that declared page geometry. Source
qualification must also prove BLKGETSIZE64 target inspection preserves the
exact byte count without rejecting a non-4096-aligned tail; later geometry
helpers alone floor that identity to complete pages.
The physical real-swap qualification capacity helper, RAM-index estimator,
sustained replay geometry oracle, and post-boot maximum logical-sector verifier
must likewise use only complete pages for allocation while keeping the
unfloored target byte count for identity. Native and rootless regressions cover
1, 2048 and 4095 trailing device bytes, plus rejection of malformed values,
fewer than two complete pages and impossible authority capacity. The source-contract
capacity oracle and nested identical-replay regression must assert that a
partial trailing page preserves the same logical capacity rather than
expecting the old alignment refusal. This does not
weaken the independent SWAPSPACE2 header/bad-page layout admission gates.
The native source contract must reject restoring prefix-only `nullb` disk
identification: the kernel constructor requires a decimal-only suffix,
in addition to the harness's independently verified driver/device identity.
The source contract in
`tests/runtime/native/ram-metadata-admission-test.py` runs under native
`test-codec` and in the ordinary `make fast_test` build step (including
resume). It proves production compressed extents remain payload-only, the
physical target retains an immutable module-load qualification token defaulting
off, and the qualified primary loader sets that token only for artifacts bound
to the exact qualification report. This source check is **not** loaded or
physical qualification. Exact-source `make test` must pass the loaded
algorithm/RAM stages before any evidence-validating loader may set the token;
real-SWAPSPACE2 payload/CRC/read/GC and header-preservation evidence remain
separate physical qualification.
Backing-header source contracts must distinguish the physical partition from the
fresh mapper: physical admission parses the full ordinary Linux swap v1 layout
and derives a bounded RAM clean-segment map, while the mapper created by swapz
must retain the strict contiguous `SWAPSPACE2` validator after `mkswap`. Tests
must not require the old strict backing validator once bad-page/tail geometry is
represented only in RAM.
Native recovery recognition must accept only the original byte-identical
SWAPSPACE2 header, rejecting a synthetic SWZ replacement. Cross-namespace
mount admission must be rechecked after exclusive target open and before
creating the Device Mapper target; source contracts must not require or
authorize obsolete raw-partition header writes.
Contradictory historical formatter requirements below are superseded.

The native repository-policy regression must keep current operator-facing
documentation aligned with this architecture. Live README evidence text must
describe byte-exact **header preservation**, never header recovery, and must
not reintroduce a separate or independent recovery-storage device as a
physical-admission requirement. Historical documents may retain rejected
recovery narratives only when they are explicitly marked non-current. The
regression normalizes prose whitespace so Markdown wrapping cannot bypass or
spuriously fail this operator-facing contract.

## Official interface

The root checkout exposes three test tiers:

~~~sh
make fast_test
make test
make test_full
~~~

`make fast_test` is a nonqualifying development loop. `make test` retains
source, native, ownership, W=1/W=2 and loaded RAM checks, omitting only
rootless package/DKMS and systemd integration fixtures. After all RAM stages
pass its overall result must remain INCOMPLETE: the physical source-admission
parent currently refuses unauthenticated run/target identity, so no actual
physical partition is tested. `make test_full` retains the previous
five-stage rootless integration and loaded RAM qualification. Its PASS is
current-source RAM/integration evidence only, not actual DKMS installation,
physical-media testing, or cold-boot acceptance. Neither tier may select an
arbitrary physical device or weaken ownership, byte-exact readback, or safe
teardown gates. Complete the audited physical admission protocol before any
algorithm production PASS is enabled.

The isolated Make-interface fixture must use a temporary `main` checkout with
no remote and a deterministic synthetic host identity. This exercises report
binding without relying on CI host metadata or enabling publication; it must
not add a production identity override or claim host qualification.

Report-admission fixtures that target a later rejection must satisfy every
earlier gate with valid synthetic values. In particular, a fixture testing
incomplete qualification stages must provide the valid
`RAM_BACKED_NULL_BLK_ONLY` scope and matching source identities, so the
production gate order is exercised without weakening it.

When the caller does not provide a GNU Make jobserver, the private reporter
automatically chooses a bounded build width from the CPUs available to the
process (maximum 16) and creates jobservers only for independent compilation.
An inherited jobserver takes precedence. Operators do not need to choose a
manual `-j` value; qualification stages and privileged device sessions remain
strictly sequential.

The Phase 1 rootless concurrency audit is source-controlled in
`tests/tools/rootless-resource-policy.py`. It classifies the exact literal
rootless phase inventory plus every dynamically iterated `bash -n` script
as read-only candidates, private-fixture candidates, or serial-only hazards.
The contract regression in `tests/runtime/native/test-report-test.py` must
reject added/renamed/unreviewed phases, changed syntax-script lists, duplicate
labels, unknown resources and shared read/write conflicts.
Its dynamic-loop drift fixture must replace one actual source-list token while
preserving the loop's grammar, proving rejection by the exact path allowlist
rather than by a malformed shell construct. Shared Make/native
artifacts, fixed disassembly paths, reporting/history fixtures, diagnostic
relays, process/descendant cleanup, and package/systemd simulations remain
serial pending explicit isolation evidence. A private-workspace classification
is a provisional source audit, not a proof against future shared-state edits:
re-audit when a test's subprocesses, output paths or ownership behavior change.
Native build remains a mandatory predecessor of every candidate.

This matrix is planning-only: no worker scheduling, concurrent stderr relays,
parallelism option, new public Make goal, changed test order, or relaxed safety
and qualification gate is authorized by Phase 1. Phase 2 must independently
prove per-worker isolated outputs/first-error attribution, bounded resource
admission, cancellation/reaping and teardown before allowing any overlap.

Phase 2 enables **automatic CPU-aware rootless scheduling by default**:
plain `make test` (or `make test_full`) detects available CPU affinity and
cgroup CPU quotas, using as many workers as there are admitted independent
tasks and available CPUs, without requiring `SWAPZ_ROOTLESS_JOBS`. The optional
`SWAPZ_ROOTLESS_JOBS=1` remains a serial diagnostic fallback, and
`SWAPZ_ROOTLESS_JOBS=2` preserves the earlier pilot behavior; unknown
overrides fail closed. A single-core host automatically uses serial execution.
The native Make compilation jobserver remains independent of this setting.
Only three adjacent, source-declared groups execute concurrently: source
contracts with swapzctl provenance, production-readiness with direct rootless
evidence, and the 19 read-only Bash syntax checks. No unsafe task becomes
parallel just to fill idle cores. All other rootless suites, privileged
lifecycle operations, and hardware-dependent loaded/RAM/physical performance
benchmarks remain serial and resource-isolated; the test sequence, requirements
and number of cases are unchanged.

The private `tests/tools/rootless-parallel.py` coordinator selects a CPU-aware
worker budget and validates the
complete Phase 1 inventory and pairwise resources before executing only its
hardcoded commands. Each worker has an independent process session and
mode-0600 stdout/stderr/status files in a newly owned mode-0700 directory;
worker stdin is disabled. Nested Python processes inherit a no-bytecode-write
environment so two workers never mutate the shared Python cache. It dispatches
up to the CPU budget (and never more than the admitted group size), stops
*new* dispatch after a failure, lets started tests
finish their own cleanup, and
kills/reaps a worker on its 900-second individual timeout. A worker that exits
zero while a descendant remains in its process group is instead marked failed
(status 125) and the group is terminated; timeout and signal cleanup also
escalate after the leader exits, so descendants ignoring SIGTERM cannot remain
running. The private worker status includes a separate cleanup flag, so an
ordinary worker exit 125 retains its original failure classification. The Bash parent
alone replays output and emits source-ordered progress rows, using actual
per-worker elapsed times; it keeps only a bounded private failure diagnostic
and cleans up completed scratch.
An unexpected failure or signal also runs the owned scratch cleanup before
the standard rootless reporter disables traps, without replacing the first
failure status. The top-level console announces CPU-aware rootless scheduling and the
independent compilation budget on separate bounded-width lines, while keeping
loaded and hardware-dependent benchmark qualification sequential. The pilot must not reinterpret elapsed-time
markers as PASS evidence, nor mix shell output from independent workers.
`tests/runtime/native/test-report-test.py` tests exact group approval,
multi-worker overlap, single-core fallback, affinity/quota budgets,
private output permissions, stop-dispatch on failure and
bounded timeout/reaping using synthetic unprivileged processes.
The test fixture asserts inherited bytecode suppression with a simple
Python statement so its one-line synthetic worker remains valid source.

The native production-C suite may compile the unchanged production sources
once into shared, compiler-configuration-bound objects, then link the existing
independent test executables. Shared object reuse must track included headers,
compiler/preprocessor flags, sanitizer configuration, compiler version and
target, host architecture selection, and the source-controlled native build
rules; changing any of those inputs invalidates the objects and dependent
executables. A rule-only main update must never reuse an artifact
whose compile/link dependency graph came from the prior Makefile. The
hermetic build-rule regression must verify both a no-op incremental invocation
and a rebuild after setting the copied Makefile's timestamp strictly newer
than all native artifacts, without sleeps or wall-clock assumptions. Never
merge independent assertion/failure boundaries or omit ASan/UBSan/TSan
qualification for speed.
The native/rootless stage records separate native Make and remaining-contract
wall times as optional observational evidence, not qualification PASS gates.
Print the optional rootless timing breakdown once after **all** verdict rows
(including the development-only physical trial row when present), never
between rootless and loaded progress rows. Retain the breakdown in the
canonical report even when stdout cannot be published, and regression-test
contiguous rows using an authenticated synthetic rootless timing marker.
The official `make test` and `make test_full` terminals present one
unified, globally numbered `ID | Suite | Name | Verdict | Time` progress
table for rootless suites, loaded benchmark families, five top-level stages,
and the optional development-only physical algorithm trial. Its header
appears once; there are no separate rootless/loaded/stage progress tables.
Top-level stages appear together after execution, with explicit `NOT RUN`
rows for stages skipped after a failure. Detailed benchmark measurement
tables and interpretations remain separate from this verdict table.
The source-contract regression must assert the unified table producer and
authenticated loaded-progress emitter rather than a retired printed
loaded-suite heading. Fixed-width suite cells include the delimiter space
after the eight-column padded suite label; tests must assert that alignment.
The rootless fixture asserts the source-controlled display-name capitalization,
and the authentication fixture checks the complete Git credential-helper
argument without inspecting or revealing credential data. Synthetic official-run mocks must accept the optional
observational progress-table argument and still preserve the first exit code
on report-write failure. The physical trial remains separately
authorized, and its status cannot be interpreted as production physical
acceptance. Original protected admission observations and failure-only
diagnostics remain readable outside the table; they are not test verdicts.
The internal ID36 pressure gate is shown as "Low-memory + heavy-CPU stress
test" in the progress table; its internal ID, timing marker, evidence schema,
and required qualification conditions remain unchanged.
Rootless and loaded progress share the same five columns and continuous IDs.
Every source-defined
suite has a unique, short, descriptive display name rather than a repository
path; the exact path stays in authenticated progress markers, private
diagnostics and report evidence for debugging. Human-readable acronyms
such as I/O are allowed and are not treated as repository path prefixes. Interactive terminals prefix
each `RUNNING` row and its completed replacement with carriage return,
yielding one visible row per test. Both the official unified stream and
isolated direct-stage regression path preserve this terminal convention. Redirected logs emit only one terminal row per suite,
without control sequences. An unfinished suite gets a single `FAIL` row for
nonzero exit or `INCOMPLETE` if its completion marker is missing after zero
exit. Loaded qualification uses the unified progress table, displaying each
source-controlled phase or benchmark family once, with a short descriptive
name instead of hundreds of internal START/PASS and per-pair markers. Live
terminals rewrite the active RUNNING row; redirected logs only print completed
rows. PASS requires a matching phase-specific success marker; DONE represents
only an observational elapsed-time boundary, not a qualification PASS. Failed
or interrupted phases end as non-PASS rows. Full loaded child transcripts,
individual benchmark evidence, negative-case refusals and original first-error
attribution remain available in the existing private/report artifacts.
The eleven expected fault-injection BLOCKED refusals remain authenticated
against the exact captured case matrix but are not printed as separate table
rows; an unexpected BLOCKED or FAIL remains a non-PASS terminal row and
the existing stage failure summary preserves the original attribution.
Generic BLOCKED/FAIL summary text must redact relative as well as absolute
child-supplied paths without masking single-letter I/O or A/B diagnostic
abbreviations. A known preflight BLOCKED marker must remain BLOCKED in its
single displayed row, not be mislabeled FAIL.
A synthetic report-contract fixture may contain authenticated negative-case
records without a top-level lifecycle START boundary; such a fixture must
not demand a lifecycle display row that the child never started.
Loaded-phase elapsed times remain separately retained in the report.
The rootless stderr-relay pass fixtures must preserve and authenticate the
harness's fixed START/PASS phase markers before comparing the unchanged child
stdout and private stderr. Allow nonnegative integer elapsed seconds rather
than assuming initialization takes exactly zero seconds; an extra or missing
progress line must still fail the fixture. Fail-only private capture and
first-error attribution remain independently enforced. Progress is strictly
observational, filters labels against the source-controlled allowlist, and
must never print raw child output or promote a successful suite to overall
qualification PASS. A progress event with an unsupported state, malformed
numeric duration, unallowlisted suite name or wrong sequence number must be
ignored rather than displayed. On failures, retain the existing first-error
attribution and private diagnostic log; an unfinished suite is displayed
as one non-PASS row.
A bounded per-suite rootless breakdown uses Bash's built-in SECONDS and
source-controlled phase labels; the loaded reporter attributes wall time from
existing streamed markers to preflight, lifecycle, fixture preparation,
individual matched benchmark families, ID36 and terminal cleanup. Both
breakdowns are optional observational report fields, never new qualification
gates, session scheduling changes, or substitutes for per-I/O latency.
Each visible owned-RAM benchmark pair also records bounded monotonic-uptime
elapsed milliseconds for setup, fixture, replay, verification and ownership-
safe teardown. The optional `benchmarks.owned_pair_phase_timings` report
field stores only complete, ordered five-phase pairs and their execution
indices. Raw-read fanout pairs keep their full output in private logs while
relaying only fixed, bounded timing lines to the parent reporter. The
optional `benchmarks.owned_pair_timing_coverage` reports the number of
complete pairs and observed timing records, with COLLECTED, NOT_RECORDED
or REJECTED status; an interrupted session may remain unrecorded. The helper
never shares resources between pairs, never changes the official benchmark
workload, and timing-read or display failures do not alter verdicts.
Each owned benchmark mapper still undergoes independent UUID and backing
identity checks. After creation, its read-only status is captured once and all
eighteen existing fixed-policy assertions are evaluated against that same
snapshot before replay. Missing or rejected status remains BLOCKED. This
eliminates seventeen repeated status subprocesses per pair without reusing
devices, removing matched observations, or changing teardown. Existing
five-phase timings establish any actual host wall-clock savings.
### Phase 5: three-host optimization validation (nonqualifying evidence analysis)

`python3 -B tests/tools/validate-optimization.py --manifest /path/to/phase5.json`
compares copied `test_results.json` snapshots without running commands, opening a
mapper, changing global state, or publishing an artifact. This **does not**
replace `make test` or turn algorithm `INCOMPLETE` into physical PASS. Collect
all snapshots from ordinary owner `make test` runs, preserving original report
bytes under distinct filenames **before** a later run overwrites them. Do not
change `main` while a qualification run is in progress. The script neither
switches branches nor changes the official benchmark matrix.

The manifest has schema `swapz-optimization-validation-v1`, two complete
`baseline_sha` and `candidate_sha` source revisions and three `hosts` entries
with distinct profiles `x86_64-v2`, `x86_64-v4` and `aarch64`. Each host supplies
its actual 64-hex-character `host_id_sha256` and an ordered `pairs` array of
`{"baseline":"report-path.json","candidate":"report-path.json"}` entries.
Optionally add both `baseline_time` and `candidate_time` keys to every
pair, referencing GNU `/usr/bin/time -v -o <path>` sidecars produced by the
same owner `make test` commands. The validator then compares whole-command
wall, user CPU, system CPU and maximum reported RSS separately from RAM-stage
elapsed time. GNU time high-water RSS is not an additive or synchronized
whole-tree memory peak; optional physical prompts can distort whole-command
wall time. Mixed presence of time sidecars within a host fails closed.
Paths are relative to the manifest file. Five or more independent paired
repetitions per host are needed before an exact one-sided sign test can yield
p <= 0.05; fewer repetitions remain **INSUFFICIENT_REPEATS**. The ISA profile
labels are operator-declared, **not** inferred from `host_identity.architecture`;
confirm the hardware CPU capability outside the report. All runs must use the
same host ID and kernel release within each host, the pinned SHA for their arm,
all five RAM stages PASS, identical 52 rootless and 25 loaded phase labels,
50/50 complete lifecycle cases, 89/89 owned benchmark pairs with 445/445 phase
records, benchmark PASS verdicts, and a common trace/fixture/device/workload
fingerprint. Mismatches fail closed rather than producing comparable numbers.
Overall `INCOMPLETE` is admitted **only** for all-five-stage-PASS RAM reports;
failed, blocked or malformed reports are rejected. Physical qualification
remains independent.

The output separates per-host baseline/candidate median *RAM stage sums*
(rootless and loaded stages separately), per-pair setup/fixture/replay/
verification/teardown distributions, paired saved seconds and exact one-sided
sign-test probabilities. A positive result is a **reduction signal**, not a
causal performance or production qualification decision. Full `make test`
wall-clock time includes optional physical admission and publication; the
five-stage sum intentionally excludes that potentially interactive time.
Replay peak RSS, ID36 cgroup memory peak, aggregate host CPU busy and CPU PSI
are compared as **scoped diagnostics**, not whole-test peak resident memory,
process CPU, or controlled background noise. Any resource regression, missing
quiet-window evidence, changing source/build/workload, or differing skipped
test semantics still requires an operator review before default promotion.
Never infer workload identity merely from matching run durations. Repeating
source-pinned runs does not justify claiming physical storage endurance or
causality from host load changes. When reports are insufficient, record the
`INSUFFICIENT_REPEATS` or `REDUCTION_NOT_DEMONSTRATED` outcome without weakening
or silently dropping acceptance requirements.

Example manifest (replace host hashes and paths with actual source-bound copies):

```json
{
  "schema": "swapz-optimization-validation-v1",
  "baseline_sha": "1111111111111111111111111111111111111111",
  "candidate_sha": "2222222222222222222222222222222222222222",
  "hosts": [
    {"profile": "x86_64-v2", "host_id_sha256": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", "pairs": [{"baseline": "v2/before-1.json", "candidate": "v2/after-1.json"}]},
    {"profile": "x86_64-v4", "host_id_sha256": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb", "pairs": [{"baseline": "v4/before-1.json", "candidate": "v4/after-1.json"}]},
    {"profile": "aarch64", "host_id_sha256": "cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc", "pairs": [{"baseline": "arm/before-1.json", "candidate": "arm/after-1.json"}]}
  ]
}
```

One pair per host is intentionally below the statistical threshold. This
read-only comparison must run before recommending opt-in concurrency as the
default, deleting a benchmark, weakening cleanup, or changing physical gates.
The primary lifecycle rootless audit emits per-unittest-method monotonic
elapsed milliseconds (including per-case setup/teardown) from its existing
in-process runner. Write and flush each bounded source-defined marker on
unittest's original progress stream after the case verdict, retaining the
existing private stderr relay even when a case redirects Python's sys.stdout.
A separate direct-stdout write can race the asynchronous stderr relay and
splice a timing marker into a progress line, so it is not admissible. The
reporter stores only contiguous indexed cases whose
class and method are present in that suite's source AST under the optional
rootless-stage `primary_lifecycle_case_elapsed_ms` field. The corresponding
`primary_lifecycle_case_timing_coverage` records expected/accepted/observed
counts and COMPLETE, PARTIAL, MISSING, REJECTED or SOURCE_UNAVAILABLE status
when the suite started. Missing or rejected telemetry does not become a
qualification failure or a fabricated duration. Class-wide setup and runner
startup remain outside individual case times; compare their sum to the suite
total before considering any fixture reuse. Timing is descriptive, not
authorization, qualification, or a separate public test command.
Missing or malformed timing evidence must not alter PASS/FAIL/BLOCKED. Sensitive child
output must never become a phase label. A protected identity read may use
only the fixed, bounded, pinned, read-only noninteractive privileged fallback. If its authorization or trust checks
fail, the host identity remains UNAVAILABLE; no insecure file mode change,
substituted machine ID, unbounded read or privileged checkout execution is
authorized.
The CI Make-policy guard must recognize exactly six public root goals,
require explicit algorithm/full tier routing, and retain the restriction on
directly invoking privileged provisioning from a root recipe.
The tier-routing regression must prove the same five source/native/kernel/
RAM stage calls are preserved, the algorithm rootless command uniquely selects
`--algorithm`, and an all-PASS RAM stage array cannot qualify a physical
device. The full-tier fixture retains the original RAM PASS semantics.
Its mocked loaded phase must initialize the ordinary optional
`delta64_prepare` benchmark record as NOT_RUN before reaching the report
admission gate; absence of unrelated fixture fields is not physical evidence.
Rootless failure-attribution unit fixtures must extract only the wrapped
package/systemd child recipes, excluding their surrounding tier-selection
control-flow delimiters. Preserve the final newline of every extracted child
recipe, so the following fixture command cannot concatenate with the retained
failure's source-line argument. This keeps first-error attribution independent
of tier guard syntax without executing unrelated packages in synthetic tests.
On the single canonical `test_results.json` publication path, a same-source
algorithm-tier INCOMPLETE report must never replace full-suite evidence,
including a recorded full-suite failure. Earlier five-stage reports without
a tier field remain full-suite evidence. Full-suite runs can supersede
algorithm-tier reports; rootless or RAM-only evidence never becomes physical
PASS. This precedence guard applies before the publisher's initial Git push,
not only during concurrent-push retries.

The hermetic incremental Make-interface fixture exercises `make test_full`,
which preserves the original five-stage RAM build-order and exact-artifact
PASS/refusal contract. It must not treat an algorithm-tier physical-INCOMPLETE
result as a compile failure or weaken its no-op rebuild checks.
Hermetic shell-recipe regressions using a substituted native output directory
must stage their own compiler-configuration and shared-object prerequisites
before creating fake test executables; those fixtures must not silently compile
or execute real native tests in place of the shell behavior under test.

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
A definite non-`EINTR` `swapon` or `swapoff` failure is the first error at
that syscall boundary and must return before any post-call inventory probe can
replace its errno. Successful or interrupted calls still require the existing
independent post-call inventory proof; an inventory failure there remains the
reported error. The source-extracted rootless transition regression must pair a
definite `EBUSY` with a synthetic later `EIO` and prove `EBUSY` is retained,
while the matching `EINTR` case reaches the proof and reports its `EIO`. Native activation must request
Linux released-swap-cluster DISCARD by combining `SWAP_FLAG_DISCARD` with the
kernel ABI `SWAP_FLAG_DISCARD_PAGES` bit (`0x40000`). It must not request
`SWAP_FLAG_DISCARD_ONCE`, must not alter swap priority, and must not retry
with zero flags after a definite activation error. This policy requests
asynchronous whole-cluster notifications; it does not promise an immediate
per-page DISCARD when a process exits. The rootless lifecycle source guard
must bind both ABI bits and the single native syscall expression.

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
The direct-C owner-claim regression must complete run A, let run B claim the
same partition with a fresh run ID, reject stale A-side ACTIVE/COMPLETE and
recovery-state writes, and prove B's canonical state bytes remain unchanged.

When START, STOP or RECOVER has already failed, a best-effort durable
`RECOVERY_REQUIRED` publication is secondary recovery bookkeeping and must not
replace the operation's first errno. If that publication also fails, return the
original numeric errno, report the secondary numeric recovery errno separately,
retain the transaction evidence, and remain fail-closed without publishing
ACTIVE or COMPLETE. Public diagnostics for this boundary must not expose the
run ID or private resource names. The rootless
`tests/runtime/native/primary-lifecycle-nullblk-qualifier-test.py` regression
compiles the production errno-preservation helper with an injected
recovery-state write failure for START, STOP and RECOVER; source ordering must
bind all three failure epilogues to that helper before any success publication.
The rootless errno fixture must seed a bounded private STARTING, STOPPING or
RECOVERING state file before each child and inspect that file after the child
exits. Exercise a synthetic failure before state mutation, a failure after
RECOVERY_REQUIRED becomes observable, and a successful write. The pre-write
failure leaves the interrupted bytes observable; the post-write failure may
already expose RECOVERY_REQUIRED even though persistence still reports failure.
This mirrors the production replace-record ordering where temporary-file
fsync and close precede rename, followed by recovery-directory fsync. An
injected post-mutation rename or directory-sync failure can expose new bytes
while publication remains failed and durability UNCERTAIN. No observed stage
alone establishes durable success. In all
cases preserve the original numeric errno, report the secondary recovery errno
for failed persistence, and reject failure-path ACTIVE/COMPLETE reporting.
Synthetic file fsync does not establish production directory durability,
mapper state or kernel swap state. A source-extracted record-writer fixture
must also simulate close failing after descriptor release, rename failing both
before and after a visible replacement, and temporary-unlink cleanup failing
after file fsync. A failed close must not publish a new canonical state, and
any cleanup errno must leave the first writer errno unchanged. Only verified
successful rename and recovery-directory fsync permit durable publication.
The canonical diagnostic name for this sequence is
`state-file-fsync-close-rename-directory-fsync`; diagnostics must not retain
the obsolete rename-before-close ordering.

A same-run `.primary-state.json.<run>.tmp` left before rename is unpublished
state, not a lifecycle stage. Before any later state replacement, the held
partition lock and exact active/consumed owner claim must be revalidated, then
a root-owned mode-0600 single-link regular temporary may be unlinked. That
unlink must be followed by a recovery-directory fsync; failure blocks the
current write. If a later retry observes the name already absent, it may
continue to the normal replacement, but success is still impossible until the
replacement's existing recovery-directory fsync completes, which also closes
any prior ambiguous unlink. This keeps the normal no-temp fsync ordinal
unchanged. A stale transaction must not unlink another run's temporary, and
symlink or otherwise unsafe temporary identities must be preserved and refused.
Metadata-only READY reconciliation is a distinct owner-proof path because READY
may be durable before the active marker is created. After the held partition
lock, canonical READY run ID and exact consumed record are verified (and the
active marker too when present), it may reconcile only that run's deterministic
unpublished state temporary before the READY-to-COMPLETE replacement. This path
must not require an active marker, must never name or remove another run's
temporary, and must retain the same unlink-plus-directory-fsync durability
requirement before continuing.

A failed owner-marker unlink or release-directory fsync never qualifies STOP or
RECOVER as COMPLETE, even when an in-process directory read finds no active
marker. Under the per-partition mutation lock, a subsequent metadata-only
reconciliation of COMPLETE with no marker must retry recovery-directory fsync;
failure blocks the next owner claim and retains the consumed run record.
The retry does not itself assert kernel swap or mapper cleanup, which the
completed durable transaction must have established before marker release.
Run identity and protected path values must not enter public refusal logs.

Rootless lifecycle evidence must source-extract the production record writer
and assert three distinct results using synthetic mode-0700 directories:
pre-rename file-fsync failure leaves original state bytes and original errno;
post-rename/pre-directory-fsync failure returns its errno even though new bytes
are observable (durability remains UNCERTAIN); and successful fsync permits
publication. A separate source-extracted COMPLETE-owner reconciliation must
block a new claim if its retry fsync fails, with an explicit skip-fsync mutant
that proves premature success would be caught. STOP/RECOVER source-extracted
swapoff gates must demonstrate a definite injected EBUSY prevents any mapper
removal call, with a bypass mutant proving the oracle is sensitive. Lifecycle
refusals must name the operation, first numeric errno, recovery-state errno
when it also fails, the persistence boundary and honest durable/mapper/swap
observability (OBSERVED, UNOBSERVED or UNCERTAIN). Source-extracted fixtures
must never execute privileged swap, mapper or device operations.
Generated STOP/RECOVER snippets that retain production observation updates
must declare their `swap_observation` and `mapper_observation` locals in the
fixture wrapper and consume them in the fixture's assertion output. Original
and mutated source-extracted fixtures must compile with the same `-Werror`
flags: if a negative-control mutation removes the final reference to a static
syscall adapter, give that test adapter deliberate external linkage or another
safe reference instead of suppressing warnings. The private owned-null_blk
fault binary links the full production coordinator with `--wrap=syscall`, so
its no-fault path must explicitly forward every production syscall reached on
the lifecycle admission path. On x86_64 and arm64 this includes the
`statmount` and `listmount` namespace-inventory syscalls (457 and 458); the
standalone fake-kernel passthrough harness must execute both forwards. A
synthetic `ENOSYS` from the test seam is fixture failure, not lifecycle
refusal evidence. Unrecognized syscall numbers remain fail-closed.
The fake-kernel calls must match production's `finit_module` options, discard
flags and `/proc/self/fd/N` swap pathname, and `/proc/swaps` open flags.
Underlying syscall failures must preserve their original errno and fake kernel
state, including when an applied-`EINTR` injection is selected. A post-call
inventory fault may be armed only after real swap success or ambiguous
`EINTR`; a definite underlying failure must leave later inventory forwarding
unchanged so the shim cannot manufacture selected-fault evidence after the
causal syscall error.

The qualifier's report-host fixture must match the production
`trusted_host_record` implementation: pin DMI product UUID and machine ID with
no-follow descriptors, validate their stable file identities, and hash the
exact `swapz-host-v2` byte layout. Source-extracted shell regressions must
retain complete compound-command boundaries. The missing-by-PARTUUID control
must execute the final alias refusal outside its polling loop, and cleanup
extraction must include the current post-removal udev-settle guard. A
parser-only generated C harness that includes the complete production
translation unit may suppress only unused-static-function warnings; all other
warnings remain fatal, and the normal production C build continues to check
the full file without that suppression.

Observation labels are proof labels, not syscall-attempt labels. A successful
idempotent helper that proves swap already inactive or a mapper already absent
records OBSERVED even when its *_by_call output is false. Conversely, a
mutation-attempt flag may become true before the independent post-mutation
proof completes; if that proof fails, the corresponding state is UNCERTAIN
rather than OBSERVED. START, STOP and RECOVER update diagnostic observations
only after the full proof-returning helper succeeds. At the owner-marker unlink
plus recovery-directory fsync boundary, a failed STOP or RECOVER reports
durable=UNCERTAIN even when the COMPLETE state record itself was previously
observed. Every START admission-detail refusal repeats the original errno,
persistence boundary and durable/mapper/swap observations.

Stale-run state-write coverage exercises the production owner-claim gate, not
a replacement predicate. With a newer run active, stale ACTIVE and COMPLETE
swapz_primary_state_write_at() calls plus stale
swapz_primary_state_require_recovery_at() fail before parsing or replacing
the newer canonical state. State bytes and the newer owner marker remain
byte-for-byte unchanged and the fixture does not print either run ID.
Lifecycle source-order audits must follow the shared helper to its state-write
dependency instead of requiring the persistence call to appear inline in each
coordinator body. Audit the ordinary preprocessed executable function bodies,
so comments, diagnostics and inactive preprocessor branches cannot satisfy the
contract. Each operation-specific epilogue must invoke the helper only after
capturing the first errno and before publishing success, and the helper must
issue exactly one executable recovery-state persistence attempt. Isolated
START, STOP and RECOVER source mutants must reject omitted or
preprocessor-disabled recovery persistence and premature ACTIVE/COMPLETE
reporting.
Because `SWAPZ_PRIMARY_ROOTLESS_TEST` compiles out those privileged lifecycle
callers, keep the production-only static helper out of that build's translation
unit while continuing to compile its actual body in the isolated errno fixture;
the rootless manager build remains warning-clean under `-Werror`. Any generated
production START-coordinator fixture must also include the extracted helper
after its recovery-state test seam is defined, so the actual caller and helper
compile together without an implicit declaration.

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

The post-COMPLETE owner-release durability boundary is an additional
rootless diagnostic (not part of the 18 loaded interruption phases or the 13
negative loaded-recovery cases). A private regular-file fixture compiles the
actual production owner-release and recoverability C functions with the
existing directory-fsync fault shim. Executable-code guards additionally
require both production stop and recovery coordinators to persist COMPLETE
before owner release, attribute that call to the owner-release phase, branch
to failure when it returns an error, and preserve the original errno. If the
directory fsync fails after unlinking the active-owner marker, the original
EIO and owner-release failure must remain visible; the earlier durable COMPLETE
record is not permission to report successful teardown.

The private fixture does not inspect Device Mapper or the kernel swap inventory,
so its diagnostics must label mapper and swap state UNOBSERVED rather than
claiming absent or inactive kernel state. Failure diagnostics must distinguish
expected from observed durable/owner/recovery state and use NOT_RUN for a
recovery attempt that has not actually executed. Source ordering separately requires
the current COMPLETE recovery rejection to occur before mapper/swap cleanup
calls. Fresh fixture processes must remain BLOCKED with byte-exact COMPLETE
state whether the unconfirmed unlink is modeled as persisted or the prior
marker is modeled as present, and repeat attempts must preserve that same
private state. The loaded repeated-recovery-after-COMPLETE check must require
process exit 2, the fixed `PRIMARY_RECOVER=FAILED phase=admission errno=1`
record with honest UNOBSERVED resource fields and its matching
`BLOCKED: primary-swap recovery failed: Operation not permitted` line.
No extra sideband output is accepted; a mismatch reports only bounded marker
presence and exit status, never arbitrary coordinator output. This exposes
an owner-release retry/progress gap; it is not loaded evidence and does not
prove kernel mapper/swap ownership or teardown.

### Primary cross-namespace mount admission evidence (issue #94)

On an ambiguous pinned mount-namespace scan, production must continue
to refuse admission. For an EAGAIN from the direct namespace walk, emit a
fail-only, bounded mount-scan step and numeric errno, without host, PID,
namespace, mount or device identifiers. The loaded reporter may attribute
that step only to a matching coordinator initial/repeated cross-namespace
preparation failure; it must reject malformed or contradictory child markers.
This diagnostic never upgrades a BLOCKED run into permission to retry or
mutate physical storage. The private loaded null_blk prepare verifier must
permit exactly one canonical mount-scan record only alongside the matching
initial/repeated cross-namespace EAGAIN refusal (errno 11), then re-emit that
record with the normal canonical prepare failure. The same strict step/errno
matching also accepts the scanner's source-controlled EINVAL (errno 22) and
ENOSYS (errno 38) kernel ABI refusals, without reason, peer-root or private
fields, only at fixed namespace-fd, namespace-id, root-object, init-root,
root-walk, mount-list, listed-mount and root-revalidation steps. For EINVAL
from a malformed opened mountinfo snapshot, only
`step=mountinfo-read errno=22 reason=malformed-mountinfo-frame` (empty,
unterminated or NUL-containing framing) or
`step=mountinfo-parse errno=22 reason=malformed-mountinfo` (invalid table
syntax) is admissible. Every such result remains BLOCKED; it does not
establish a clear inventory or authorize mutation.
Duplicate, malformed, unmatched or free-form sideband output remains FAIL;
the original admission refusal remains BLOCKED. Rootless regressions cover
both scan phases and reject mismatched errno, duplicates and private values.
At the coordinator's init-root step, an EAGAIN can include one fixed
`reason=` classification identifying a failed root-type, inode, process-root
device, init-root device, or init-root statx observation predicate. The verifier
and report parser must allowlist only these cause labels with `step=init-root`,
reject injected host values and unrelated steps, and preserve the original
admission refusal without exposing the compared inode or device values.
For `reason=process-root-device-mismatch`, the fail-only marker must also
classify the already-observed PID 1 root device as
`peer_root=matches-process` or `peer_root=differs-process`. The distinction
is a single-snapshot observation, not proof of a stable host layout or
permission to relax admission. The `make test` stage summary must include
that bounded root comparison and a non-mutating next step when PID 1 agrees
with the coordinator but mountinfo disagrees. No additional host identifiers,
syscalls, retries, or alternate test commands are authorized.
Root admission distinguishes two independent identities: the root mount
superblock device from mountinfo must match the seeded `statmount` SB_BASIC
device, and the coordinator and PID 1 root `statx` inode/device must match
each other at both observations. These device-number classes may legitimately
differ on a Btrfs subvolume. The full pinned namespace inventory, target/
parent checks and stable root mount ID remain mandatory; mismatched root
objects, mismatched superblocks, or changes during the scan refuse admission.
A root superblock inconsistency emits only the fixed
`root-superblock-device-mismatch` reason at `root-walk`. Rootless production-C
regressions must cover the Btrfs-style stable case and the negative cases of
a hidden mounted target, mismatched root objects, mismatched superblock, and
root changes after inventory.
The production `statmount` caller must provide the complete 512-byte fixed
Linux UAPI buffer even when requesting only SB_BASIC|MNT_BASIC; a 56-byte
prefix is not a valid compatibility buffer on newer kernels. The production-C
fixture models EOVERFLOW for a shorter buffer. Fail-only mount inventory
diagnostics may classify errno 75 as `statmount-buffer-too-small` at
`root-walk`/`listed-mount`, `root-parent-depth-limit` at `root-walk`,
or `mount-count-limit`/`listmount-overflow` at `mount-list`; no host
identities or raw mount IDs are emitted.



The direct-C mount reader fixture must exercise the actual production reader
with private, regular-file proc inventories: selected partition and parent
only in a foreign visible PID, a sibling before a selected row, an unreadable
PID directory, an enumeration error after returning a valid PID, and an opened
foreign mountinfo descriptor whose read or close fails. A namespace disappearing
during an opened-table failure remains unsafe and must still refuse.
Only an unopened PID table with a separately proven absent mount namespace
may be skipped for process-exit errors. Preserve the coordinator's own root
mount identity independently from the foreign namespace's root.
Top-level `/proc` enumeration is not complete thread coverage: Linux does not
return non-leader `/proc/<tid>` directories from `getdents(2)`, while mount
namespace membership can differ per thread. The direct-C fixture must therefore
keep the process leader clean while placing a selected partition or selected
physical parent only in a synthetic `/proc/<pid>/task/<tid>/mountinfo`, and
require refusal; an unrelated sibling in that non-leader thread remains a
positive control. For the coordinator's own non-leader task, first admit a
sibling-only table while the leader remains unchanged, then replace only the
task's table with a selected mount and require refusal. Each thread-only
selected/parent assertion must independently prove that its task-specific
mountinfo was actually opened, so an inherited leader conflict cannot satisfy
the case accidentally; coordinator-task coverage must also prove that opened
descriptor closes. Inject unreadable task mountinfo on the task path only and
require proof that the task-specific injection fired, so a leader access error
cannot satisfy that case. Reject malformed non-leader task mountinfo, fail
closed when a reused TID changes its mount-namespace identity between the initial and
confirming stats, and permit a task already absent at namespace inspection.
Source-extracted fixtures must include the production helpers called by the
extracted reader, including `swapz_primary_mountinfo_full_root`, and model its
`/proc/.../root` observations for synthetic tasks without consulting the host
PID tree. Compile the real reader and its mutation-negative control with the
same strict warning flags so missing fixture dependencies or host-process
lookups cannot hide the intended admission test.
A missing foreign leader `ns/mnt` marker is not evidence that the whole
thread group exited. Exercise leader disappearance at every pre-task-scan
window: absent at the initial namespace stat, lost between the same-namespace
identity stat and its confirmation, and lost after an unopened leader
mountinfo returns an exit-class error but before the follow-up namespace stat.
Across those timings cover both a selected-partition worker and a
selected-parent worker. Production must observe the task as busy or fail
closed as BLOCKED, never admit on leader disappearance alone.
If the leader namespace marker is absent, production must still enumerate an
available `/proc/<pid>/task` directory and inspect its visible non-leader
namespace and mountinfo records; it may skip the leader table but must not
skip the task inventory. For fixture cases that intentionally keep one worker
namespace and mountinfo readable, require exactly one task-specific mountinfo
open even if the reader ultimately returns a fail-closed error; an unrelated
earlier refusal at the vanished leader does not satisfy the regression. Only a separately proven absent task inventory can
establish that no visible worker remains. The fixture must recreate a live
non-leader `ns/mnt` marker for every case so results cannot depend on prior
test order. If the selected mount is reported busy, prove
task-specific mountinfo was opened; preserve the coordinator's root identity,
original errno on error, and closure of owned descriptors. Report the
admission phase, missing/stale identity class, expected versus observed
decision, and a safe read-only retry, without printing host task, namespace
or selected-device identities.
Directly exercise the production non-leader helper at the shared visible-task
ceiling and aggregate mountinfo-byte ceiling, requiring EOVERFLOW without
constructing millions of synthetic proc entries.
A production scanner must enumerate those task views (or
establish equivalent complete namespace coverage) with the same bounded,
fail-closed rules. Count thread-group leaders and non-leader tasks against one
4,194,304-entry ceiling, and apply the aggregate 64 MiB mountinfo-byte limit
across parsed leader and task tables. A single opened table may exceed the
ordinary 64 KiB stack read buffer: grow to no more than 1 MiB with allocation
only when required, accept only a complete, strictly parsed table, and refuse
larger tables with EOVERFLOW. An opened table at the old 64 KiB boundary
must not be mistaken for an unsafe/empty table; fixtures must include valid
tables above 64 KiB and oversized tables above 1 MiB. Keep generated valid
large-table fixtures below their independent 1,024-mount synthetic-inventory
capacity; use longer valid rows to exercise byte growth rather than mount-count
exhaustion. Source-extracted direct-C late-race fixtures must import both
`SWAPZ_PRIMARY_MOUNTINFO_INITIAL_BYTES` and
`SWAPZ_PRIMARY_MOUNTINFO_BUFFER_BYTES` from production source when compiling
the extracted mount reader. Their oversized-table negative controls must
expect the source reader's fixed `SWAPZ_PRIMARY_MOUNT_INVENTORY_FAILURE`
`step=mountinfo-read errno=75 reason=per-table-byte-limit` marker before
the coordinator failure record, with exact marker ordering and without
admitting arbitrary or host-private sideband data. Preserve the 64 MiB
aggregate gate and surface fixed, host-private-ID-free reasons
`per-table-byte-limit`, `read-overflow` or `aggregate-byte-limit` with
errno 75 on `mountinfo-read` or `mountinfo-aggregate` steps. Revalidate each task's namespace identity
after reading its mountinfo; a task that changes namespace during the read must
refuse the inventory. A task-directory enumeration failure or a still-present
namespace whose mountinfo cannot be opened is ambiguity and must fail closed.
This is a stable inventory blind spot, not a post-snapshot TOCTOU observation
and must not be labelled UNPROVEN.
Also cover a chrooted peer whose mount-namespace device/inode matches the
coordinator while its process-root-filtered mountinfo is empty. The coordinator
may skip that redundant view only after its own mountinfo has a valid root row
and its pinned direct namespace walk is complete. Do not treat
`readlink("/proc/self/root") == "/"` as namespace-root proof: Linux reports
that string after the same process chroots to the root of a child mount, and
after a normal switched-root boot whose namespace top remains rootfs. For the
coordinator, require its process-root directory to match `/proc/1/root` by
device and inode, require the seeded `statmount` superblock device to
match the root device parsed from self mountinfo independently of Btrfs inode
`st_dev`, and revalidate both root objects plus the process-root unique
mount ID after direct inventory. A stable
switched-root child mount may pass only after the parent walk reaches the
self-parent namespace root and `listmount`/`statmount` completes from that root.
A different chroot root, a mismatch between mountinfo and the current `statx`
root, or a root change during inventory must refuse with `EAGAIN`. The fixture
must prove the direct inventory actually ran, and separately cover a selected
mount hidden from the process-root view, a root ABA, a distinct PID 1 root, an
unavailable PID 1 root, and a process-root change during the scan. An empty
table in a foreign namespace remains ambiguous and must fail closed. Include a
regression proving the shortcut cannot hide a selected-device mount already
present in the coordinator's table.

For the opt-in host-bound same-root-parent scope, keep the direct production-C
mount-namespace controls independent from the scope-policy and late-race
fixtures. Model a root partition and selected target with distinct synthetic
device numbers on an assumed common physical parent; the root partition and
unrelated sibling mounts remain positive inventory controls, but a selected
target mounted locally, as a bind mount, as a foreign namespace root, or under
another PID still refuses by exact major:minor despite misleading source
labels. A mounted physical parent also refuses. Under the same synthetic root,
malformed or unreadable foreign tables and incomplete PID enumeration must
remain failures. A same-namespace chroot shortcut must not hide a selected
mount already present in the coordinator's full-root table. Also inject a
selected-target mount after that local full-root table has been read but before
a same-namespace peer is identity-checked and skipped. If the current bounded
reader still returns its earlier clean snapshot, report that observation as
**UNPROVEN** with `prevented=none`; do not call it a PASS and do not lock the
unsafe result into an expected-failure assertion. A future reader that observes
the target or fails closed is acceptable. This within-scan race is part of the
same non-atomic exclusion problem as a change immediately after the final
snapshot returns, but it starts earlier and can span the remainder of PID
enumeration.

Independently retain the foreign-post-snapshot negative control with an exact
timing witness. Begin with the peer leader and task views clean, require the
fixture to observe the peer leader mountinfo through read-to-EOF and successful
close, complete that peer's non-leader task scan, and inject the selected-device
row only when production returns to the top-level `/proc` iterator. An EOF from
`/proc/self/task` or `/proc/<pid>/task` is too early and does not establish
this boundary. A fresh production-reader call must observe the injected row.
If the original bounded read remains clean, report **UNPROVEN** with
`prevented=none`; never convert that observation into a PASS or expected FAIL.
Because this direct reader fixture intercepts no header write, mapper, mkswap
or swapon operation, its diagnostics must report those mutation hooks as
`NOT_INTERCEPTED`, not zero. Failure diagnostics must name the snapshot
boundary, selected/parent/sibling case, observed errno, and remaining
reader-only proof limitation.

Check production target/root-parent topology gates for changed, identical and
unresolved identities. Runtime ownership lives on tmpfs and therefore has no
recovery-device ancestry or independent recovery-parent gate. The
reader supplied an out-of-date parent argument may return a clean snapshot:
this is a positive *reader-only* negative control, not physical admission;
callers must independently re-resolve ancestry, compare against the original,
and reject changed topology. Log the rejection category (selected target,
sibling/root, namespace enumeration, device ancestry, or unresolved identity).
These synthetic facts cannot authorize the host-bound scope, certify physical
device ancestry, or close either the within-scan or post-snapshot mutation
exclusion interval.

Process and namespace identity must not be conflated when interpreting these
regressions. A numeric PID/TID is reusable; PPID can change through ordinary
reparenting while the parent's PID and `/proc/<pid>/stat` start ticks remain
constant. Start ticks are sampled at kernel clock granularity, not a retained
reference to a task. Comparing two `/proc/<pid>/ns/mnt` stat device/inode
tuples identifies the observed mount namespace, not the lifetime of the PID,
its parent, or the atomicity of its mount table. Two equal stat observations
can span task reuse into the same namespace or an intervening namespace ABA
transition. This reader does not own a pidfd or namespace fd while
identifying peers. A pidfd pins task identity, while a namespace fd pins the
namespace's lifetime and identity; neither pins the task's filesystem root or
freezes mount changes. An opened mountinfo fd pins the namespace and filesystem
root selected at that open, but it does not pin the earlier PID/TID lookup or
make the later inventory-to-mutation interval atomic. The rootless parent-reparent
reproducer establishes only that an observed parent tuple may change without
parent replacement; it does not establish a matching primary mount-reader
path or a destructive admission. Preserve **UNPROVEN** for unclosed snapshot
intervals; do not label them FIXED solely from repeated namespace stats.

A mount-namespace device/inode match also does not prove that a foreign
`/proc/<pid>/mountinfo` view is complete. Linux captures the target task's
filesystem root when opening mountinfo and omits mountpoints outside that root.
An isolated rootless user/mount-namespace probe must therefore distinguish a
full-root view from a chroot-filtered peer view: a private harmless mount may
remain present while a fresh process-root-filtered mountinfo omits it. A second
probe must cover **root ABA**: the same live PID/start ticks can report `/`
before and after a mountinfo open performed during a temporary chroot, while
that opened descriptor remains filtered. Pre/post root strings are therefore
not completeness proof.

For any otherwise-clean mountinfo view in a distinct mount namespace, primary
admission must pin that task's mount-namespace descriptor, obtain the task-root
mount's unique ID with `statx(STATX_MNT_ID_UNIQUE)`, walk
`statmount(STATMOUNT_MNT_BASIC)` parent IDs to the namespace-root mount, and
enumerate that pinned namespace with `listmount` plus
`statmount(STATMOUNT_SB_BASIC)`. Resolve the pinned namespace descriptor
through `NS_GET_MNTNS_ID`, available since Linux 6.11, and supply that
stable 64-bit ID in the request's `namespace_id` field; the reserved
32-bit field must be zero, never a file descriptor. Keep the namespace
descriptor open for the entire read. The native fixture must simulate
that ioctl and reject unavailable IDs (`ENOTTY`, `EINVAL`), a successful
zero ID, and any unrecognized ioctl, without treating them as permission
to inspect a less complete mount view. Compare every returned superblock device
number against the exact selected partition and physical parent. The focused
production-C fixture must keep filtered leader and non-leader mountinfo
syntactically clean while this direct namespace inventory contains a hidden
selected partition or parent, and require busy or fail-closed rather than
admission. It must also inject direct-inventory failure and prove the pinned
namespace descriptor closes. On the project's x86_64 and arm64 targets,
production uses the architecture-common Linux syscall numbers 457/458 even when
libc headers predate the `SYS_statmount`/`SYS_listmount` names; when those
names are present, compile-time assertions must agree. The synthetic fixture
may define the same numbers solely for its intercepted seam. Neither case
asserts the running kernel implements all required mount-namespace ID and
inventory syscalls: runtime `ENOSYS` or an unsupported request remains a
fail-closed admission result.
The syscall seam must independently inject `ENOSYS` and `EPERM` into
`statmount` and `listmount`, force more than one 256-ID `listmount`
batch with the selected device only in a later batch, and fail closed when a
later batch errors after an earlier clean batch. A stacked-mount control must
return an unrelated covering mount ID before a covered selected-device ID and
require the scanner to inspect both IDs exposed by `listmount`; this proves
scanner traversal, not arbitrary stacked-filesystem backing ancestry. A listed
mount ID that disappears before `statmount` must refuse with its original
`ENOENT` rather than become a clean end-of-list result; inject that race
against an ID actually returned by `listmount`, not an ordinal syscall count.
Cover selected partition and physical-parent entries beyond the synthetic
fixture's former 512-entry ceiling, with a far-index unrelated sibling as a
positive control. Each far-index control must prove that its final synthetic
mount ID reached `statmount`; a clean sibling result alone is not pagination
evidence. The fixture itself must return `EOVERFLOW` if its bounded synthetic
namespace cannot be represented and prove that its capacity path supplied that
error; silent truncation is never evidence of a clear mount inventory. These
reader-only controls do not prove zero destructive actions by the lifecycle
coordinator or exclude privileged post-snapshot changes.

For causal mount-inventory refusals, the production-extracted reader regression
must attribute the first failing foreign namespace syscall by numeric
syscall (statmount 457 or listmount 458), injected numeric errno,
namespace class and listmount batch index. Test distinct EACCES
versus EPERM denials, missing syscall ENOSYS, disappeared listed-ID
ENOENT and a second-batch listmount EIO after the first clean
batch. The reader must return a failure with the originating numeric errno;
an incomplete inventory must never become a clean or mounted-target result.
The lifecycle callers must separately handle a reader error (preserving its
errno) and a completed inventory reporting the target mounted (policy denial).
A combined error-or-mounted check that overwrites both branches with EPERM
violates causal errno preservation, even when it still refuses admission.
The rootless reader fixture has no physical mutation hooks and must report
NOT_INTERCEPTED, not claim measured zero intercepted writes or kernel-atomic
mount/swapon exclusion. Post-snapshot physical exclusion remains UNPROVEN.

The separate production-extracted late-race coordinator fixture must compare
the exact fixed `SWAPZ_PRIMARY_MOUNT_INVENTORY_FAILURE` parse marker before
the ordinary coordinator refusal for malformed complete mountinfo records.
Both local and remote malformed cases retain `EINVAL`, zero destructive
actions and redacted diagnostics. Empty remote and truncated local/remote
mountinfo tables must separately compare the exact framing marker
`step=mountinfo-read errno=22 reason=malformed-mountinfo-frame` before the
coordinator's unchanged EINVAL refusal. Oversized input retains its
independent errno 75 marker. These cases must continue to prove zero header
writes, mapper creation, mkswap and swapon and must not hide a new producer
diagnostic by weakening or dropping the exact-stderr assertion.

If unique mount IDs, foreign-namespace statmount/listmount, namespace identity,
or any listed mount cannot be proven, admission is BLOCKED; never fall back to
the filtered table. The namespace-fd request form requires Linux 6.18, but the current
coordinator uses the kernel-assigned namespace-ID request form supported
since Linux 6.11. Older kernels or unavailable ID retrieval remain BLOCKED;
never guess a namespace ID or use the filtered mountinfo view as a fallback.
The coordinator may retain its mountinfo-derived process-root device fact only
after `statx` identifies a stable process-root directory whose device and
inode match `/proc/1/root`, and both that device and the seeded mount's
`statmount` superblock device exactly match the root device parsed from self
mountinfo. The seed may be a child mount in a normal switched-root layout; the
parent walk must reach the self-parent namespace root and the complete
`listmount`/`statmount` inventory must start there. A self root-link string of
`/` is insufficient. A distinct process/PID 1 root, a mismatch with the
mountinfo root, unavailable PID 1 identity, a root change during inventory, or
an incomplete namespace walk refuses. Before using the same-namespace
shortcut, the coordinator must also complete the pinned namespace inventory
for its own namespace and revalidate process/PID 1 root identity.

The direct namespace walk is still a bounded snapshot, not a mount lock. PID
reuse or root ABA after the namespace descriptor is pinned cannot hide an
already-present mount in that pinned namespace, but a new mount after the
final listmount completion, inaccessible PID namespaces and other
post-snapshot changes remain UNPROVEN. This is separate from the
same-namespace shortcut,
which is permitted only after the coordinator proves its own root is exactly
`/` and has already validated its full-root table.

Do not promote a synthetic initial namespace-`stat()` `EINVAL` into a
production defect unless a matching Linux procfs path is established. The
mountinfo open path itself can use `EINVAL` while a task is disappearing, so
the errno is not globally synonymous with malformed input. The contractual
cases remain source-specific: malformed mountinfo preserves `EINVAL`, while a
namespace identity change detected after a successful table read refuses with
`EAGAIN`. A still-live task whose initial namespace stat somehow returns
`EINVAL` remains **UNPROVEN** until a matching kernel path is reproduced; any
production change for that case stays with the production owner.

The optional rootless `unshare` child-failure control must first run an
assertion-free namespace-setup probe with its own child-start marker. A nonzero
preflight before that marker is an environmental SKIP; if the marker was
observed, a nonzero preflight is FAIL. After a successful preflight, a missing
test-child start marker, an unexpected child error, or a wrong namespace
identity is FAIL and must never be reclassified as setup unavailability. Keep
an open parent namespace fd as the pinned namespace reference for the
comparison rather than passing raw host namespace device/inode values through
argv or diagnostics.

The primary-start rootless lifecycle fixture must independently show a
foreign-PID conflict on the initial admission, a different visible PID appearing
between scans, and the same numeric PID retaining its name while its mount-
namespace identity changes before exposing a selected mount. Inject ambiguous
late inventory errors as well as conflicts, including an opened mountinfo close
error and a `readdir()` failure only after at least one foreign PID has been
processed. For every rejection before the module/device mutation boundary, assert the
captured production failure phase and *original* errno, zero intercepted module
loads, mapper operations, `mkswap` and `swapon`, and retention of the READY
or recovery-requested owner state. A mount-conflict diagnostic may identify that
category only when the actual production mount-facts call returned
`target_mounted`; fixture scenario selection alone is not evidence. Non-mount
refusals may cite validated phase/errno/zero-mutation evidence, but must not be
mislabelled as an independent subsystem gate when the refusal is a mount-
inventory parse or access failure. Case diagnostics must identify the safe
conflict category and which mutation was prevented without printing private
proc paths or run IDs.
The generated-C fixture must capture a complete bounded refusal record: a
START denial may emit both `PRIMARY_START=FAILED` and
`PRIMARY_START=ADMISSION_DETAIL`. Size the capture for both records and treat
read errors or a full buffer without confirmed EOF as a fixture failure with a
bounded diagnostic, not an assertion abort or a truncated comparison. Expected
`durable=OBSERVED` reflects the validated READY state and manifest, whether the
conflict is found during initial admission or the final recheck.
The late-race coordinator fixture models the raw backing as already inactive
when it reaches START: it must intercept
`swapz_primary_transition_original_swap()` as an explicit no-op lifecycle
boundary before the exclusive target open. This fixture does **not** prove an
active raw-swap `swapoff`; the separate pre-swapoff revalidation and lifecycle
tests own that destructive transition. Current START performs three mount-fact
passes on a successful late-race case—initial admission, the pre-swapoff
revalidation, and the later pre-mapper revalidation—with exactly one late
pre-mapper pass after fixture injection. A missing transition seam, implicit
declaration, or stale two-pass expectation is a harness failure.
The three exclusive-open identity negative controls (wrong device number,
wrong geometry and stale PARTUUID) must activate their synthetic fault at the
post-raw-swapoff interrupt seam, after pre-swapoff admission but before the
production target exclusive-open reinspection. A later module-intent injection
would test prewrite revalidation instead and misattribute the refusal phase.

Keep a negative control that removes final pre-mapper revalidation and
demonstrates one intercepted no-op raw-swap transition boundary followed by one
module load, mapper creation, mapper-only `mkswap` and `swapon`. Match those
actual counter fields; a removed raw-header-write counter must not make the
negative control fail its own evidence check.
The post-target selector negative control must remove exactly one executable
guard, independently of the surrounding explanatory comment's wording.
Evidence created **after** the last successful
read-only snapshot, including a new mount, swap activation or now-unreadable
PID inventory, is an explicit **UNPROVEN** exclusion interval: do not relabel
it as a prevented mutation or as loaded kernel safety. Closing #94 requires
separate loaded evidence of the kernel-side exclusion and recovery behavior;
snapshot-only rootless results cannot provide that proof.

The primary late-race generated-C test must also compile and execute the
production selector identity and checked-open functions against private
rootless regular files. After reading a valid selector, replace its named inode
with identical or different PARTUUID bytes, replace or remove the protected
configuration-directory inode, and substitute a symlink. A change between
parsing and final descriptor/name verification must retain `ESTALE` and clear
the output; a later independent successful read must observe the current
selector instead of caching a prior read. At the checked-open boundary, swap
the named alias for a different regular-file inode between pre-open stat and the
opened descriptor, require `ENODEV`, and verify byte-for-byte that the private
target is untouched. The unchanged safe control may open the current private
target but must leave all header bytes unchanged. Immutable SWAPSPACE2
header/digest semantics are covered separately by the production-C primary
policy test. For the coordinator's pre-exclusive-open check, changed PARTUUID,
dev_t and geometry must return `ESTALE` with zero intercepted module, mapper,
`mkswap` and `swapon` actions. These checks must use the
extracted real production functions in dependency order, compile with
implicit-declaration warnings treated as errors on x86_64 and ARM64, and
report phase, expected/observed identity and original numeric errno without
private target identifiers. When two extracted helper groups share a production
dependency (for example PARTUUID normalization), emit that function exactly
once in the generated translation unit; a duplicate definition or an implicit
declaration is a harness failure, not product evidence. They prove bounded last-use validation only;
they do not freeze the configuration or kernel mount/swap inventory after
the final read and cannot grant physical activation.
The mutation-sensitive coordinator controls must use the extracted production
protected-selector reader for the **initial** successful configured-target
selection; an in-memory PARTUUID variable is not sufficient evidence for this
boundary. After that successful read and before the coordinator's prewrite
inventory check, independently replace: (1) the selector inode with a different
valid PARTUUID, (2) the selector inode with identical bytes, and (3) the
protected configuration-directory inode with an equivalent selector. Each
fixture must prove the inode or directory identity actually changed. A stale
admitted selector that reaches any of the four intercepted mutations is now
a **FAIL**, not an acceptable UNPROVEN outcome: require production `ESTALE`,
zero header writes, zero mapper actions, zero formatter calls and zero swapon
calls, plus a phase/mismatch-class/first-errno diagnostic with no protected
identity bytes. The STARTING recovery marker must remain owner-controlled.
The independent control with an unchanged selector must still complete all
four synthetic actions successfully. The initial configured-target selection
must use the actual source-extracted production pathname reader. The final
selector decision must instead execute the source-extracted production helper
that bounded-reads the **retained admission selector descriptor** and compares
those bytes to the transaction manifest; a second independent pathname reader
is not equivalent identity evidence. The pinned directory/file identities must
also come from source-extracted production helpers, not hand-written models.
Include a cross-read ABA negative control that changes only an **ancestor
pathname**: while the independent reader is active, make the protected config
path resolve to a private substitute directory containing a different valid
selector, then restore the original ancestor before the outer identity check.
The admitted directory/file inodes and their metadata must remain unchanged,
so the test proves the unfixed two-reader sequence can select a transient target
without relying on ctime/mtime changes of the pinned objects. The corrected
coordinator must observe only one such initial window, then refuse the
manifest/pinned-selector mismatch with original `ESTALE`, a redacted
`selected-target-not-bound-to-admitted-selector` class, and zero
header/mapper/formatter/swapon mutations. A diagnostic reread in the
intercepted header seam cannot count as prevention; an unrelated rejection or
race never injected is also a failure. Add a post-admission, prewrite
target-geometry drift control and a target-identity race/restoration diagnostic
control: if the first final inspection mismatches but the classification
inspection sees the admitted target again, require
`target-identity-raced-or-restored`, not a fabricated partition mismatch.
Add a same-byte selector-inode replacement injected from the final target
inspection seam, after the earlier selector content/live-name proof has
completed. Production must repeat the admitted selector live-identity check
after successful target revalidation and refuse that replacement with original
`ESTALE`, the redacted selector-file mismatch class and zero intercepted
mutations. A source-extracted negative-control mutant that removes only this
post-target selector check must reach header/mapper/formatter/swapon, proving
the regression is ordering-sensitive rather than satisfied by an earlier
selector snapshot. The existing selected-parent and root-parent substitution
controls must refuse before any mutation. The unsafe baseline has successful
initial/final mount reads, four independent swap-inventory observations and no
false mount conflicts. Keep the separate post-final-snapshot
mount/swap/inventory races explicitly UNPROVEN: no rootless read-only recheck
demonstrates atomic exclusion or binds a physical reader across device-number
reuse.
The source-extracted coordinator must intercept both admission-time and
failure-classification target-inspection calls with the same private fixture.
Source-extracted target-parent and root-parent drift controls must compare
the production's full bounded identity-class diagnostic. Prewrite refusals
after persisted STARTING require the preserved first `ESTALE`, an explicit
changed-parent class, `STARTING_PENDING_RECOVERY_UPDATE` diagnostic state,
and zero intercepted mutations; initial READY refusals must still retain
`READY` in their diagnostic. Distinguish changed root-parent identity from
changed root/target-parent relationship without weakening either check.
A missing inspection shim is a harness linking failure, never positive
production safety evidence. Require an actual post-admission geometry change
and at least one observed last-use inspection, but not an incidental fixed
number of repeated inspections; the original `ESTALE` and zero-mutation
contract remains mandatory.

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
runtime override. JSON objects consumed by the physical helper must reject
duplicate keys and non-finite numeric constants rather than accept Python's
permissive `NaN`/`Infinity` extensions.

`tests/tools/qualify-primary-real-swap.py` is private Agent-8 test
infrastructure, not a second public command; Agent 12 owns registration in
`tests/tools/test-rootless.sh` and the official test pipeline. It must BLOCK in GitHub-hosted CI and must never call
`swapon`, `swapoff`, Device Mapper removal, forced module removal, or create
fallback swap itself. Activation, deactivation, and recovery are requested only
through the production primary coordinator.

Before physical activation the unprivileged admission parent must prove: exact
clean source on `main` with local
`HEAD == origin/main == validated source` and a freshly queried remote
`refs/heads/main` equal to that source (unreachable or stale remote is BLOCKED).
The privileged physical helper must not invoke Git or trust a one-shot SHA.
Instead it connects to the parent through a private mode-0600 Unix-domain
socket, authenticates the parent's unprivileged UID with `SO_PEERCRED`, and
sends a nonce-bound request at initial admission, immediately before every
cycle's `primary prepare`, and again before emitting PASS. The parent must
resolve Git through the same root-owned, non-group/world-writable executable
policy used for its other trusted commands; a PATH-substituted Git binary
cannot become source authority. The parent repeats the same
clean/local/tracking/remote-main proof for each request before deciding whether
that phase has enough independent identity evidence to authorize progress. After the clean-worktree
query, check canonical remote main and then recheck local HEAD, branch and
origin/main before approval, so persistent local movement while the network
probe is in flight is refused with bounded expected/observed identities and a
safe next action. These observations do not lock a concurrently moving remote
ref; later phases cannot reuse an earlier approval. The source-admission
parent also binds kernel-reported socket peer PID and its Linux process start
time/ancestry to the still-live launched sudo process tree. sudo may fork a
monitor, so simple equality to Popen.pid is not sufficient. Exact connection
peer identity is rechecked before each response and again after a potentially
delayed source query. Changed, missing or unreadable identity or an exited
launch owner must BLOCK. An untrusted UID-0 connector is not authenticated
merely by SO_PEERCRED UID 0. SO_PEERCRED is connection-time identity: a live
owned connector can transfer/share its connected descriptor, after which a
different process can write while SO_PEERCRED still names the connector.
Therefore connection ancestry alone is not exact message-sender proof. The
socket request is bounded by a read timeout. A nonce value repeated in a new
request is not by itself approval replay: responses bind both phase and nonce,
and the child verifies both. Reordered phases remain BLOCKED. These observations
do not prevent arbitrary code changes by a hostile root operator or guarantee
that a Git ref cannot move after the final source observation.

The rootless source-parent ownership regression must additionally observe a live
launched child PID and stable /proc start time, reject the same child once
exited, and demonstrate that an inherited connected Unix descriptor can carry
bytes from a different subprocess without changing SO_PEERCRED. This is a
negative control for exact message-sender proof, not a simulated root-UID
impersonation or physical admission. The launched qualifier must start in a
private session/process group so listener setup failure, malformed/duplicated
private messages and exhausted termination grace can preserve the first refusal,
use bounded group TERM/KILL plus direct-child wait, reap the Popen child, prove
the controlled owned group empty, and never print private request bytes. The
source-admission peer proof must also keep every peer-to-Popen ancestry entry in
that launch-owned private session; a descendant that calls `setsid()` remains
an ancestry descendant but is a wrong-session substitution and must BLOCK. A
deterministic rootless negative control must exercise that detached descendant.
The same suite must model /proc states independently of cached socket peer
credentials: an otherwise matching live peer-to-launch lineage must pass the
process-ownership predicate, while Z, X and x states for either peer or launch
ancestor must report `observed=exited_peer_process`, `errno=none` and
`authorization=BLOCKED` before source verification. A separate synthetic
stale-credential control must keep the numeric SO_PEERCRED PID and /proc
lineage apparently live while the kernel-peer lifetime is ended; the parent
must refuse with `observed=exited_connection_peer` before reading a request
or checking source. Failure to obtain `SO_PEERPIDFD` must retain its numeric
errno and BLOCK rather than fall back to PID/start-tick inspection, and the
fixture must prove the handed-off peer descriptor is closed. These controls do
not attest to the message writer.
A rootless descendant that ignores SIGTERM is a required negative control: direct-
child-only cleanup must not be accepted as complete. Exit observation for a
marked session leader must use a non-reaping wait boundary until group-wide
termination has been issued, so PID/process-group reuse cannot precede cleanup.
A repeated initial nonce
must never grant or reuse approval; these controls still do not establish target,
reader, detached privileged descendants, or sudo teardown on the physical host.

The normal rootless runner must register
`tests/runtime/native/primary-real-swap-parent-ownership-test.py` exactly once,
immediately after the primary real-swap contracts and before the terminal oracle
contracts. Its live-process negative controls run without sudo or device writes;
first-failure attribution and bounded private stderr must be retained through
the shared rootless reporter. Its synthetic error control must retain the
original child exit/errno, expected versus observed process-group state, and
cleanup outcome in a mode-0600 private diagnostic, with only redacted bounded
failure attribution in public summaries. A passing regression reports only
synthetic subprocess-ownership safety, never approval for physical admission.

The reciprocal source-admission **client** must authenticate the known living
unprivileged creator of the admission listener, not merely a same-UID
replacement endpoint: the socket's inode, mode and ownership, the kernel
SO_PEERCRED PID and UID, the client's pinned pre-connect ancestry segment
through that parent with /proc start ticks, and a live pidfd must agree on
connection and again before and after each approval. The client must select the
**nearest ancestor with the parent's effective UID** (the second Uid field in
/proc/PID/status) as the only creator candidate and stop the pinned lineage at
that process. Merely finding the peer anywhere in the ancestry would also trust
a higher same-UID shell or launcher which could replace the socket. Conversely,
ancestors above the authenticated parent are not authority; their exit or
reparenting must not revoke an otherwise unchanged live parent. At connection
and each approval boundary, require exact `(PID, PPID, start_ticks)` equality
for every intermediate ancestry entry. For only the terminal authorized
parent, require exact `(PID, start_ticks)` equality while freshly validating
its parseable /proc identity, effective UID, live pidfd, unchanged socket inode
and kernel-credentialed reply sender. The unprivileged launcher must bind its
own PID and start ticks into the commit-bound child arguments before launch;
the client must require that launch-bound identity to be the terminal
authorized ancestor and pin its pidfd before connecting, so creator exit
cannot transfer
authority to a higher same-UID ancestor or replacement listener before the
first capture. An upstream PPID change does not excuse
PID reuse, a changed intermediate link, unavailable /proc identity, listener
handoff, unauthorized child, stale session or incomplete proof. The rootless
three-process reparent regression must observe the intermediary exiting,
the terminal parent's PPID changing with stable start ticks, and a genuine
nonce-bound synthetic approval. Separate negative controls must reject a stale
launch-bound creator before any socket connection and reject missing /proc
identity. Rootless execute-path fixtures that mock the source-admission client
must still supply and assert propagation of the mandatory launch-bound parent
PID and start ticks; otherwise they only exercise the earlier incomplete-channel
refusal and cannot qualify cleanup/error-preservation behavior. Neither result
authorizes physical admission. The rootless
AF_UNIX regression must reject that higher-ancestor listener, including after
it replaces a real nearest parent's socket, while preserving a direct parent's
synthetic approval. Recheck the selected effective UID at every approval
boundary; malformed or unavailable process credentials are BLOCKED.
The client must enable SO_PASSCRED and verify
SCM_CREDENTIALS on every received reply byte; SO_PEERCRED alone remains
unchanged if a connected descriptor is passed to a foreign writer. Missing,
truncated or foreign sender credentials, a swapped pathname, an exited parent,
changed ancestry/start time or unavailable evidence must BLOCK before source
approval. The source-bound rootless socket-substitution probe must run twelve
real AF_UNIX attempts against the actual client and observe
`check=parent_ancestry` as the first failed authenticity invariant for an
unrelated same-UID listener, with no request delivered to the genuine parent.
Separate real AF_UNIX regressions must preserve a legitimate synthetic
parent-child nonce-bound reply and reject forged replies sent through passed
descriptors, changed socket inodes, malformed/duplicate JSON and wrong nonces.
Every authentication refusal retains the failed phase/check, expected proof
class, observed safe class, numeric original errno when present (otherwise
`none`), BLOCKED authorization, and a read-only next action; no private
socket path, PID, reply payload or source material is logged. Pidfd pins process
lifetime against PID reuse, while /proc start-time/ancestry protects process
identity; neither alone proves message authorship. In-memory admission-sequencing
fixtures that are not themselves testing pidfd acquisition must provide a real
disposable descriptor as the synthetic connection peer pidfd and stub only the
live-lineage proof; a generic `getsockopt` byte mock must not accidentally turn
the fixture into a malformed-pidfd test. The bounded unadmitted-child teardown
fixture must assert that this synthetic peer-pidfd acquisition was actually
reached before it evaluates refusal cleanup and timeout/kill precedence.
Specifically, the malformed/duplicate private-request cleanup fixture must
provide a live disposable pipe fd through the SO_PEERPIDFD mock, assert
acquisition and descriptor close, and stub only the unrelated process-lineage
proof. It must still launch and reap a real child, reject duplicate keys
before any source check, and withhold the private request payload from stderr. The parent still lacks
independent authentication of the privileged **request** writer, and no
rootless synthetic approval supplies selected-card/reader or last-use physical
evidence. Physical source-only admission remains unconditionally BLOCKED.
A deterministic two-card/two-reader rootless control must give both devices
the same historical PARTUUID, major:minor, size and model but distinct
synthetic physical identities. It must additionally prove that the current
source-only admission schema produces identical requests for those two devices:
the synthetic card/reader labels are test witnesses and must not be smuggled
into the request as authorization. After a valid source check, each identical
request must refuse with `request_writer_identity=UNPROVEN`,
`owner_authorization_material=missing`,
`fresh_card_reader_identity=missing`, `card_reader_identity=UNPROVEN` and
`physical=BLOCKED`; the owned synthetic child must be reclaimed. This proves
wire-level inability to distinguish the colliding devices plus fail-closed
behavior, not actual physical-device discrimination. Extra child-claimed
target, reader, invented/unknown serial, or authorization-token fields must
instead fail first at request parsing, before Git provenance or any reply, with
the sanitized `check=request_identity` class, exact source-only-schema
expectation, no private field value, and `errno=none`. Kernel peer-credential
acquisition failure must retain its original numeric errno and report
`check=peer_credentials`; mismatched peer UID uses that same first-gate class
with `errno=none` and refuses before the request is read. Missing live /proc
peer identity retains its original numeric errno. These controls prove
only source-parent refusal: synthetic identity labels are not hardware serials
and cannot serve as owner authorization. Independent owner-protected immutable
card **and** reader binding, plus fresh observation tied to the exact opened
target at last safe use, remain required on the physical host.

The current wire schema carries source, helper and control-input identity but
no independently authenticated exact message sender, physical qualification
run, selected-card/reader target, or required boundary evidence. Consequently
no current admission request, including `initial`, may receive PASS:
`physical_admission_identity_missing` is returned before any physical mutation
or terminal PASS. A future protocol may admit a phase only after it binds the
exact owned sender/run, phase, selected target and reader, plus the evidence
required at that boundary. Missing, stale or mismatched identity is never
permission to continue. Requests must arrive in exact `initial`, `cycle-1..N`, `final` order. A concurrent push,
parent disconnect, malformed/duplicated JSON, peer-identity change, missing
approval or unavailable remote blocks before the next durable transaction/card
mutation or prevents the final PASS. The unprivileged parent itself performs no
swap, Device Mapper, module, block-device or primary lifecycle mutation. Current qualification
provenance; a frozen production acceptance manifest; the protected PARTUUID
selector; exact partition size and device number; and the selected partition's
verified parent topology. The default requires
`root_same_physical_disk_as_target=false`. A separately owner-authorized host
may cross that root-parent gate only with the exact root-owned mode-0600
`/etc/swapz/primary-root-parent-scope` record bound to a combined hash of the
hardware DMI product UUID and live `/etc/machine-id`, root and target partition
identities/geometries, stable parent identity, and complete non-overlapping
partition-table layout. The hardware UUID prevents an authorization record
from following only the bootable USB disk to another computer. Re-read all
scope facts through the opened target descriptor immediately before the first
target write. Missing, malformed, stale or ambiguous authorization remains BLOCKED;
never emit raw host, serial/WWN or record fields in refusal diagnostics. The
read-only plan may show only the non-secret SHA-256 scope fingerprint needed
for an administrator to provision the exact root-owned record; it does not
grant authority. This narrowly scoped admission exception does not alter any
frozen production-acceptance manifest or qualify the target. Runtime ownership
must be root-owned volatile state under `/run/swapz`; persistent qualification
evidence is not swap recovery storage and its physical parent is not an
admission fact.
The rootless real-swap qualification storage-separation fixture must require
an explicit boolean `root_same_physical_disk_as_target=false` (reject missing,
true, null, and numeric zero); it must not require the obsolete
`recovery_same_physical_disk_as_target=false` key because lifecycle recovery
is tmpfs-backed rather than a separate physical recovery device. No unresolved
primary transaction, mapper, module, or raw swap alias resolving to either the
selected partition or its physical parent disk; any unresolvable active
block-swap identity is BLOCKED; at least 1 GiB `MemAvailable`; readable kernel
diagnostics; and working cgroup-v2 memory, swap, PSI, OOM, and zswap controls.

Rootless shared-root authorization controls must reject absent or malformed
records; wrong host, root partition, target PARTUUID/partition number/device
number/geometry, parent identity or partition-table layout; replaced devices;
and overlapping or out-of-parent partitions. They must separately prove that
runtime ownership is confined to the expected root-owned volatile state
location rather than inventing a recovery-device parent relationship.
A production scope-layout regression must also model ordinary sysfs parent
entries such as regular uevent attributes and symlinks: classify each entry
without following links before probing its partition attribute, skip only
confirmed non-directory entries, and preserve failures for missing or
unreadable parent evidence. A rootless fixture must reproduce the resulting
ENOTDIR path without weakening partition-layout completeness.
A positive exact record fixture may test the policy predicate only. It does
not create a live authorization, waive source/artifact qualification, or
permit physical mutation or production activation.
Source-extracted lifecycle fixtures focused on a separate race boundary may
stub only the shared-root predicate to a stable positive result; their result
must not be counted as shared-root authorization evidence.

Rootless selector qualification must reproduce replacement after the first
lstat and after opening the descriptor, symlink and hard-link refusal, file
truncation/oversize, invalid/non-ASCII PARTUUID, read errno, and changed
ownership/mode. A valid unchanged protected selector is admitted; a changed
selector inode, even with identical PARTUUID bytes, is not. Per-cycle source
approval must be followed by a fresh descriptor-bound selector comparison and
the same frozen authorization-snapshot/partition/parent check before any
primary prepare. Replacement after an opened descriptor must be classified by
the named/opened inode mismatch even when unlinking the original inode also
changes its link count. A nonzero live-authorization command status or malformed
authorization observation at this boundary must likewise become BLOCKED before
prepare, retain the numeric status when available, and redact command/path
details. Each negative fixture must show BLOCKED before a primary operation,
with bounded redacted phase, expected/observed category, errno/status and safe
next action. The real-swap helper must recheck the admitted selector inode
**after** independent target inspection, preserving the first descriptor I/O
errno on cleanup failure. Revalidate the same source-bound partition, physical
parent and geometry after each completed cycle and again at final publication.
Historical authorized-target `major_minor` and `observed_path` are
observational, not live identity: a renumbered `/dev/sdb1` may pass the
*rootless consistency verifier* only when the same source-bound reader serial,
O_EXCL-requested opened target descriptor, live sole-partition/parent topology
and exact geometry match. This synthetic verifier result is not independent
card/reader authorization and does not establish kernel O_EXCL exclusion. A matching PARTUUID,
model, size or historical pathname alone must never admit a different disk or
claim physical-card uniqueness. If the historical snapshot lacks a stable
reader binding, the attempt BLOCKS; synthetic serial agreement is not physical
PASS. Rootless injected-control fixtures must use only intercepted descriptor,
topology and subprocess operations. They must exercise legitimate renumbering,
duplicate PARTUUID, missing/mismatched reader identity, a valid low-character-
diversity exact serial, missing parent path, substituted target or parent block inode
(even with unchanged dev_t), changed target geometry, live-name replacement,
campaign identity drift and first I/O errno retained over descriptor close
errors. All rejected identities must reach BLOCKED with
zero mocked prepare/start/write calls. Initial admission is after private
qualification import, so its fail-only record must distinguish
`owned_state_may_have_changed=true` from
`target_mutation_reached=false`, preserve a verifier child exit status without
command/path text, reduce generic verifier refusal to a bounded proof class
while retaining the first syscall errno, and require exactly one
verifier-published bound identity. The verifier must open the resolved
target once with `O_NOFOLLOW|O_EXCL`, derive device and geometry from the
opened target descriptor, open and bind the parent block descriptor separately,
and recheck both opened and named inodes after topology/source-policy
inspection. A close failure must not replace an earlier identity/geometry
errno. A verifier child-command `QualificationFailure` must propagate
unchanged so the last-use wrapper can retain its original numeric exit status;
generic path/runtime classification must not consume it. Source approval uses
only the parent's existing `cycle-N`
request before prepare; never invent `cycle-N-start`. After successful
prepare, recheck the pinned parent-process/socket authority and target proof
without sending another source request. A revoked parent-process authority
or changed target BLOCKS start, and the diagnostic explicitly says that
already-prepared owned state may have changed.
Recovery uses only the existing coordinator-owned path after review; retain
completed-cycle evidence on later refusal. This remains snapshot-only
protection: it does not make the final check-to-mutation interval atomic or
distinguish device-number reuse by a different physical card/reader.
A rootless two-cycle control must reject simulated post-cycle selector drift
before the second prepare. The already completed first cycle is allowed to
have performed its simulated prepare, but drift must permit no additional or
resumed primary mutation and must produce BLOCKED evidence. That BLOCKED
evidence must retain the completed cycle result; a refusal after teardown must
not erase an already-performed physical mutation from the audit record.
Identical bytes at
a substituted inode or protected-directory replacement are not identity proof. Two snapshots do not exclude a completely hidden selector
ABA, make the last-use interval kernel-atomic, or identify a unique physical
card and reader; physical admission stays BLOCKED without those guarantees.

The real-swap byte oracle is qualification authority: `--oracle` must resolve
to the exact source-controlled `tests/tools/primary-real-swap-oracle.py`, never
an arbitrary replacement. The unprivileged admission parent derives the
oracle SHA-256 from the exact validated Git commit object and carries that
digest in every nonce-bound admission response. After the clean-source gate
and before any admitted lifecycle mutation, the privileged helper must snapshot
the current oracle bytes into its root-only temporary workspace, require their
SHA-256 to match that commit-derived digest, record it, and execute only that
pinned copy for every cycle. An alter-pin-restore worktree race or a mid-run
pathname replacement must therefore be unable to fabricate byte-exact PASS
evidence. The source-controlled oracle must retain its Git executable bit
because the admission path explicitly checks `os.access(..., X_OK)` before
execution; the rootless terminal-contract test guards this mode requirement.
Before emitting `ORACLE_WAITING` or allocating anonymous memory, the
oracle must reject any seed that is not exactly 32 lowercase hexadecimal
characters with a bounded exit-2 diagnostic and no traceback or echoed invalid
seed. Validated seed bytes are immutable for the worker lifetime and should be
parsed once, then reused by the fill and verification loops without changing
the deterministic page-pattern bytes. A failed core-dump resource limit
(OSError or ValueError) or dumpability lock is a pre-readiness BLOCKED
refusal (exit 2): no WAITING record, anonymous allocation or traceback may
escape. The oracle emits a bounded structured refusal with the expected page/
byte geometry, original error class/errno and cleanup state. The parent may
preserve BLOCKED only for that complete phase=preflight record, exit 2 and the
initial ORACLE_WAITING boundary; unstructured exit 2, any later phase, stall,
signal death or integrity failure remains FAIL. During the readiness wait the
cgroup guard may tolerate only an already-exited owned worker disappearing so
the terminal parser can classify that refusal; a live worker leaving the
dedicated cgroup or foreign membership still fails. If the refusal races the
initial `cgroup.procs` migration, only Linux `ESRCH` plus that same structured
exit-2 preflight record may retain BLOCKED; unrelated migration errors remain
fatal and their raw error text is not exposed. Rootless terminal tests inject
both resource-limit failures and exercise both parent race boundaries.
The worker-migration failure regression asserts the helper's stable contextual
`QualificationFailure` separately from its chained original exception. It must
verify the cause type, synthetic cause text and actual `errno` value without
requiring raw cause text in the outer diagnostic; child termination, cgroup
cleanup and closure of every worker pipe remain required assertions.

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
ordinary installed binary remain disabled. The temporary coordinator must be removed explicitly on every path after it is
created, including preflight/import/plan/device/evidence-construction failures;
runtime finalizers are not cleanup authority. Terminal PASS evidence may be
committed only after that private workspace has been removed successfully and,
when the helper owns the source-admission channel, after that channel has been
closed successfully. A reported channel-close failure must retain ownership so
outer cleanup can retry it; it cannot be marked closed before the close succeeds.
The persistent envelope and nested result bind the plan-verified digest of the
exact qualification report imported before the run; they must not re-hash a
mutable report pathname after the workload. Workspace cleanup and result-input
preparation precede the final source-admission request so the last Git/remote
proof is as close as possible to the terminal evidence commit. Rootless ordering
coverage must distinguish this pre-PASS cleanup from the fallback retry in the
function's finalizer. Mocked target verification in that coverage must append
a stable synthetic target/parent identity to the real verifier's
`observed_identity` output parameter (not merely return the device numbers),
then assert that identical identity reaches every simulated cycle and subsequent
selector policy-use check. An empty mock output list is a fixture error, not
cleanup or recovery evidence. A cleanup failure
must leave or write non-PASS evidence rather than a durable false PASS. Its
SHA-256 must be recorded in persistent evidence whenever admission reaches
durable evidence creation.

The report values, private primary plan qualified/live values, embedded control
source SHA, and observed installed bytes must all agree with the exact validated
source. Before `prepare`, the physical helper must independently derive the maximum
logical mapper geometry from the admitted partition bytes using the same
allocation-free policy as production authority: reserve block zero, round
physical data down to 256-block segments, require
`max(ceil(logical_pages / 8), 512)` GC-reserve blocks, and retain one separate
256-block foreground COW segment. The helper must require the primary plan's
`logical_pages`, `logical_bytes`, `linux_swap_kib`, and
`gc_reserve_blocks` to match that independent result. After `prepare`, it
must re-check the persisted manifest's logical pages/sectors against the same
result before allowing `start`. Any stale zero-headroom geometry is BLOCKED
before mutation or FAIL after a prepared transaction; manager success text is
not capacity authority.

The plan's `privileged_execution_enabled=true` proves only the execution
authority of the binary being queried. The private physical seam still requires
its explicit test-only runtime marker. Ordinary production is compiled capable
but remains false until the owner-armed cross-boot preflight has minted a
volatile authorization bound to the current boot, exact build source, canonical
PARTUUID and target byte size. The module is deliberately absent before start, so
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
The byte oracle expands the run/worker/round seed into position-distinct 4 KiB
pages; swap-in checks every byte, counts every corrupt page and byte, and caps
only the diagnostic samples. Rootless regression must corrupt multiple bytes
in a page beyond that sample cap and prove full byte-mismatch accounting and a
nonzero result, even when a terminal record is emitted. The cgroup's OOM event
keys must be present and parseable.
An `ORACLE_VERIFIED` record is terminal only after complete byte readback
and successful anonymous-mapping close. Rootless terminal fixtures must assert
exactly one ordered WAITING/FILLED/VERIFIED sequence after clean readback,
with full page/byte counts, zero mismatches and fill-to-verify digest agreement.
A failed terminal publication after clean readback must withhold VERIFIED,
retain the original reporting errno and exit nonzero despite successful unmap.
The report-write failure fixture must assert Python's concrete exception
subclass for the injected errno (for example, `BrokenPipeError` for errno 32)
instead of assuming every `OSError` construction retains the base class name.
Closed Python text streams raise `ValueError` rather than `BrokenPipeError`;
the fill and terminal evidence publishers must retain a structured nonzero
failure with complete cleanup evidence, never an uncaught traceback.
The parent must reject reordered records, any duplicate or truncated bytes
remaining after the one accepted VERIFIED record, nonzero child exit, stalled
or signal-killed workers, and inconsistent full page/byte mismatch totals or
capped mismatch samples before aggregation. A timeout or unexpected SIGKILL
must report incomplete terminal evidence rather than successful readback. Successful child exit is terminal evidence only after EOF proves
that no unconsumed oracle output remains. Short reads, interruption and failed
unmapping must not produce a complete-looking record. Parent record-pipe wait
and read failures must preserve their original errno in the bounded terminal
FAIL and chain the private exception without exposing its raw text. Failure-only
diagnostics identify the first failure phase, fully compared versus allocated
pages/bytes, expected-zero versus observed page/byte mismatch totals, original
errno when present, and whether cleanup finished. If per-round child termination
succeeds but pipe closure fails, retain that worker in outer cleanup ownership
so bounded termination/pipe cleanup is retried before cgroup removal; the first
cleanup failure remains non-PASS even if the retry completes. Missing or
duplicate `pswpin`/`pswpout` counters are BLOCKED independent evidence,
never an implicit zero-delta observation. If a child exits before VERIFIED, the
parent may surface only a complete bounded structured oracle failure record;
partial stderr and traceback/path text remain private, while the parent still
reports the child exit and incomplete-evidence disposition. An interrupt while waiting for FILL or
allocating must fail boundedly without a traceback or anonymous allocation.
Later cleanup/reporting errors must not replace
an earlier byte/digest mismatch or its counts. If a page mismatch is already
observed before a later page-read, writable-fault or unmap failure, the first
bounded terminal error remains `byte_mismatch` with exact compared-page/byte
and mismatch totals; any later operational error is secondary, and incomplete
readback must never publish `ORACLE_VERIFIED`. A page whose full 4 KiB
read/compare completed counts as compared before the separate writable-fault
probe, even if that probe fails. Standalone oracle entry points
must reject non-integer memory sizes and page indices outside the unsigned
64-bit range before allocation or hashing. Rootless terminal fixtures must
reject duplicate-key, non-finite, non-object and non-ASCII JSON, boolean or
floating byte counters, and self-consistent verification totals that exceed
an assigned worker's exact page/byte geometry. Controller-pipe closure before
VERIFY must remain a bounded wait-verify failure with no terminal VERIFIED
record. Fixtures must assert the exact failure class for each independently
mutated cgroup, mapper, kernel, target, lower-device or byte-integrity gate and
must pair simultaneous defects to prove that the earliest evaluator gate is
retained rather than replaced by a later failure.
Diagnostic samples may contain
page/byte offsets
but not raw expected/observed values or seeds. Byte-exact comparison alone is
not evidence of actual target swap-out/in without the independent cgroup,
mapper, lower-device and kernel swap-traffic observations required above.
OOM counters must remain unchanged, including at the final post-release sample;
counter regressions cannot qualify as zero OOM events.
OOM, cgroup swap and PSI telemetry begin before FILL; guard checks enforce the
1 GiB host MemAvailable floor and stop when any rolling interval of at least
five seconds has cgroup memory PSI "some" above 85%. Earlier quiet time must
not dilute a later sustained-stall stop condition. Kernel/cgroup evidence is parsed
fail-closed: MemAvailable must retain its canonical kB unit, PSI has one
monotonic numeric total, swapz byte counters are nonnegative, and failed= is
boolean. A failed dmsetup-info query is never mapper-absence evidence by
itself; absence requires an independent readable sysfs Device Mapper inventory.
Path-inspection errors for durable state, mapper/module identity, ownership
markers and cgroup teardown are errors, not silently equivalent to ENOENT.
A constant-memory cycle telemetry sampler must complete its first host
`MemAvailable`, global memory-PSI and `pswpin`/`pswpout` observation before
the workload can begin pressure. It remains active through ordinary
stop/recovery and records only bounded aggregates (sample count, timestamps,
minimum available memory and counter deltas), so telemetry covers normal
teardown without accumulating an unbounded sample log. An interruption while
starting that sampler must signal and join the sampler thread before the
interruption is propagated.

Once persistent qualification-evidence storage is admitted and before
`prepare`, the helper must durably create a root-owned 0600 attempt record
under that validated evidence base with a fail-closed
`FAIL/qualification_interrupted_or_incomplete` sentinel. The helper updates
that record before a cycle mutates state and after the cycle returns to durable
COMPLETE, then atomically fsyncs and read-verifies terminal PASS/FAIL/BLOCKED.
A crash or kill therefore leaves persistent non-PASS evidence without adding
evidence-I/O failure points inside the live lifecycle. Pre-admission BLOCKED
outcomes must not write to unverified evidence storage; Agent 10's official
runner integration must persist those runner-level dispositions.

A `PRIMARY_START=ACTIVE` message is insufficient. The helper independently
proves the run-bound mapper name/DM UUID/device number, exact one-line `swapz`
table and backing dependency, sysfs identity, valid Linux swap header with a
fresh nonzero UUID recorded in canonical lowercase 8-4-4-4-12 text, raw backing
absent from `/proc/swaps`, exact mapper
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
Disappearance while still in the known swap inventory is FAIL. A definite stop/`swapoff` failure is FAIL and remains
the primary teardown error, but a simultaneous stop-sampler failure must be
appended rather than discarded. When stop itself succeeds, sampler uncertainty
must not skip independent post-stop mapper/module/state verification; if both
fail, both reasons remain visible. If correct teardown is too fast to prove
the inactive-before-remove interval independently, the result is BLOCKED, not
PASS. The stop sampler evaluates those transitions online and retains only
constant-size phase/timestamp/count state; a long bounded stop must not grow a
per-millisecond sample log, and online evaluation must preserve definite FAIL
versus evidentiary BLOCKED classification. No force cleanup is allowed, including error paths. Oracle-child
termination may use bounded TERM/KILL for the dedicated test processes only;
signal-delivery exit races must not mask the underlying qualification failure,
and one worker's cleanup must not wait for the other worker to leave the shared
cgroup. Removal of the dedicated cgroup still requires every worker exited.
Workers are tracked before cgroup migration. `cgroup.procs` must show
exactly those workers before pressure, must contain no foreign PID while
workers are active, may shrink only after a worker has entered its verified
exit phase and actually exited (a live worker escaping its cgroup is not
acceptable), and must be empty after every worker is reaped. Rootless fixtures
must inject live-worker cgroup escape and post-release OOM events independently
of normal guard observations. If the process inventory
of an empty preflight or final workload cgroup
is unreadable, an ordinary rmdir is still attempted; the kernel refuses that
operation for a non-empty cgroup, so an empty group is removed without treating
missing process-inventory evidence as PASS. Failure cannot silently leave that
directory behind. All parent pipe descriptors are closed even when
admission fails. A malformed or disconnected request before initial admission
must also reap the still-unadmitted privileged child through bounded TERM/KILL
cleanup; it may not fall through to an unbounded wait. Bounded protocol reads
retain multiple records from one read without blocking on partial records. Partial cgroup
creation, first-telemetry failures and evidence temporary-file failures must
clean up explicitly or expose the cleanup error alongside the original
failure. Oracle allocation close failure cannot turn a corrupt or otherwise
failed oracle into PASS and cannot hide the earlier workload failure message.
Failure to secure the private temporary workspace must explicitly remove it.
Rootless regression cases inject cgroup removal failures independently
from unreadable process-inventory recovery. The private source-admission channel also closes explicitly; failure to close
it must retain the triggering qualification error. Workload interrupts and
uncertain coordinator start/stop invocation failures must converge through the
ordinary stop/recover coordinator path before the initiating exception is
propagated. A definite returned swapoff failure remains a stop condition and
never authorizes forced mapper removal or module unload.

At least two passing cycles require new run IDs and Linux swap UUIDs, zero
initial mapper usage, no stale mapper/module/ownership state, durable
`COMPLETE`, and restored baseline swap inventory after each cycle. This
proves the non-reboot fresh-volatile-mapping property; cold-boot observation is
separate. `tests/runtime/native/primary-real-swap-test.py` provides rootless
parser, identity/provenance, traffic, byte-oracle, stop-order, disposition, and
cleanup mutants. `tests/tools/primary-real-swap-oracle.py` only allocates and
verifies memory; it configures no swap or mapper state. Agent 12 owns shared
runner/official-pipeline registration; Agent 8 must not edit that wiring.

### Qualified module LZ4 provider

The production primary loader must resolve the fixed `lz4_compress`
provider before calling `finit_module` on the already authenticated
`dm-swapz.ko` descriptor. Some kernels build LZ4 compression as a separate
module while decompression is built in. The dependency load must use a fixed
absolute kmod executable, fixed arguments with install hooks disabled, and a
minimal environment; it must occur only after the qualification report and
all three live artifact hashes match. A dependency failure is a fail-closed
module-load refusal, not permission to skip the qualified module or retry with
an unverified path. Neither normal stop nor recovery may remove the shared
provider. A rootless fixture must test provider success, failure, and absence
without running the host's modprobe.

### Loaded-preflight ownership and retained cleanup

The loaded preflight must retain executable mode 0755. The rootless runner
must `bash -n` both the original preflight and the isolated fixture copy
before any loaded operation. Multiline Bash `[[ ... == ... ]]` comparisons
must remain parseable; a syntax exit 2 is not an authorization refusal.
An unavailable `rmmod` is not a preflight prerequisite: a pre-existing idle
module has no proven creation owner, and the fixture must detect any
unexpected module-unload attempt. No holder PID may be inferred and signaled.

The preflight is an **admission gate, never an orphan-resource collector**.
A configfs `nullb-swapz-<16 hex>` name, an index, full memory-backed
attributes, matching null_blk driver major/minor, a block-node rdev, a
sole holder, a benchmark-looking mapper name/UUID, and absence of active
swap **do not establish exclusive creation authority**, individually or in
combination. A new preflight process cannot inherit the prior creator's
descriptors or exclusive claim. Neither a user-supplied token, stale session
record, nor module refcount grants that claim. Each such object remains
unclaimed and is BLOCKED for any attempt to open it as test backing, adopt it,
power it off, unlink it or remove it. However, when `dm_swapz` is absent, a
read-only preflight may count token-shaped configfs names and continue toward
a separate test-owned target. This is coexistence, not ownership: preflight
must not read those objects' block nodes or attributes, and must not mutate
them. The later loaded test must create a fresh random configfs object through
`deploy-nullblk.sh`, set its same-process ownership flag only after successful
creation, and bind all mapper I/O and cleanup to that exact newly created
object. Two complete-looking unclaimed objects remain unusable as backing;
their presence alone must not prevent a separate, positively owned object
from being qualified. An unreadable or substituted configfs inventory remains
BLOCKED. The legitimate cleanup path for an unclaimed object is creator-local:
only its original creator, acting under independently proven creation
authority and revalidated live identity, can undertake bounded recovery. A
later preflight process does not inherit those flags. If the original creator
is gone and no independent creator proof survives, recovery remains
read-only and BLOCKED. No owner is instructed to delete ambiguous objects
merely to unblock tests.

For diagnostics, read-only checks may evaluate the single-mapper inventory,
canonical major:minor, benchmark versus primary UUID namespace, dependency
name and devno, null_blk configfs attributes and index, sysfs alias and
driver major/minor, lower node rdev, partition markers, active swap aliases,
mounts, exact holder and captured configfs directory identity. Configfs
attribute pseudo-file inode numbers may be regenerated on each lookup and must
not be compared as persistent identities. Loaded preflight instead checks the
root-owned regular-file type through its pinned power descriptor; that check
does not grant creator authority to a later preflight process. The native
source contract requires descriptor type/owner checks and explicitly rejects
reintroducing cross-lookup power-attribute inode equality. Rootless null_blk
fixtures must model that privileged attribute as root-owned even when the
fixture files themselves belong to the CI account, and must include a
non-root-owner negative case that fails at
`expected_proof=pinned_power_attribute`. Before the
creator powers off its
device, it opens the named config directory without following symlinks,
compares that descriptor's device/inode/owner with the creation-time identity,
revalidates the directory entry, and opens each kernel-defined attribute
relative to that pinned directory descriptor. It verifies canonical attribute
contents and file type/owner; the `power` write is opened relative to that same
descriptor with no-follow, no-create and nonblocking flags, then its result is
verified before the directory can be removed. A matching
snapshot is **live identity only** and still refuses with
`expected_proof=creation_authority observed_proof=live_identity_only`
before the first removal. Missing, substituted, malformed, multiply aliased
or unreadable evidence must refuse at its earlier specific check; a name
reused after a snapshot or a foreign active swap cannot be cleaned up.
There is no atomic compare-and-rmdir operation: retain the existing
post-power identity checks and do not claim that a pathname removal is atomic.
Loaded preflight must use the native strict identity helper for sysfs devno
records and alternate index aliases. Any alternate disk entry is ambiguity,
including an empty directory or a dangling dev symlink. For an index-named
lower, every token-shaped configfs candidate must expose a canonical readable
index; a missing, unreadable or malformed candidate cannot be skipped as
though proven different. Shared identity readers must bound malformed records
before validation. It must reject
extra-field or duplicate nullb major records from /proc/devices and require
exactly one Block devices section; a successful cat substitution must not
normalize malformed telemetry into a valid identity.
The refusal must preserve the resolver/parser status and name the specific
expected and observed proof classes before falling back to aggregate identity.
Configfs numeric identity attributes must also be read as bounded canonical
single records; extra blank records, missing final newlines, leading zeroes or
oversized values are malformed evidence rather than values that command
substitution may normalize.
When the mapper is absent and token-shaped configfs names are present, the
preflight may report only their redacted count as
`LOADED_PREFLIGHT_NULL_BLK=retained_unclaimed`; it does not claim them and
continues only to let the official harness create a separate same-run-owned
RAM target. No unclaimed object may be opened, selected for mapper backing,
powered off or removed. An unreadable configfs listing remains BLOCKED.
Unrelated foreign index-named devices and noncanonical matching-prefix
decoys are retained without a false ownership claim. An idle loaded module
remains BLOCKED rather than being unloaded.

Every BLOCKED diagnostic must identify the failing `check`, expected and
observed proof classes, `original_errno_or_exit` (or `unavailable`),
a retained-resource action and a read-only safe next action, without
exposing private tokens, names, paths, device numbers or PID inventories.
A classified safety refusal has stable process exit status 1. Preserve an
external command or parser status exactly in `original_errno_or_exit`; do
not copy that shell status into the top-level `errno=` field, because it is
not a kernel errno. Only an independently captured syscall errno may populate
that field. Exit status 2 is reserved by the loaded wrapper for an
unclassified shell/runtime failure before a normal safety diagnostic.
Unexpected internal failures retain their actual status and are FAIL, not
ownership BLOCKED.

The loaded lifecycle's repeated `recover` call after durable `COMPLETE` is an
expected negative case. Capture and validate its terminal refusal and prove
that durable state and swap inventory remain unchanged, but do not print the
expected `BLOCKED:` command diagnostic into the stage transcript; the runner
classifies emitted blocked markers as admission failures.

The private `tests/runtime/native/nullblk-identity-test.sh` fixture must
rewrite host /proc, /sys, /dev and package paths in a single ordered pass
using path-component boundaries, and use only fake utilities and regular
files. Replacing a `/dev` root must not rewrite a nested sysfs attribute such
as `/sys/block/<device>/dev`. Its legacy path-only
false-admission demonstration is **not** counted as a preflight case.
The fixture must test an absent token-name directory separately from a
present directory containing malformed `dev` telemetry. Recreate the
synthetic directory before writing each malformed record so fixture setup
errors cannot masquerade as parser-negative coverage.
Syntax-check each generated fake command before executing the cases; a syntax
error in fixture tooling is a test failure, not evidence of a production
identity refusal.
When checking redacted diagnostics, validate `safe_next_action` against the
allowed read-only or creator-revalidation values instead of rejecting generic
words that may also appear in a phase name such as `mapper_remove`.
It must cover two unclaimed token-shaped objects, a complete-looking
unclaimed object, an untrusted old owner record and injected token hint, a
foreign decoy, ambiguous name/index aliases (including an empty alternate disk
directory, dangling alternate dev symlinks and a token-shaped candidate with
unknown index), malformed configfs numeric identity, malformed or duplicate
/proc/devices block sections, wrong null_blk
driver major, mismatched lower devno and index,
malformed mapper/swap inventory, owned and unrelated foreign active swap,
incomplete configfs attributes, foreign holders/dependencies, substituted
configfs inode, failed dependency probes and uncertain cleanup.
The fixture checks both pinned descriptor identities against path reuse,
refuses every case before destructive operations, and verifies zero
attempted mapper removal, configfs power-off/rmdir, module unload or host
swap mutation. It must preserve both the first numeric status and the
retained fake inventory. Its final PASS marker must report the actual
number of `run_case` invocations (currently 66). Synthetic PASS is not real host ownership,
loaded qualification or permission to recover the first host's objects.

### Development decision loop

The project-goal CI policy validates all six root Make targets
(`all install uninstall test test_full fast_test`). `make fast_test` remains
a nonqualifying development loop; `make test` and `make test_full`
have distinct algorithm/RAM and full rootless-integration scopes.

`make fast_test` is the owner-approved development loop, not a qualification
command. It builds the current working tree (dirty trees allowed), runs the
native and replay contract checks (including the lower-I/O window policy and
offline page analyzer), runs the root preflight, and then runs
the requested counterbalance-free raw/swapz pairs per selected ordinary
scenario through the same private owned null_blk pair helper and exact device
models used by `make test` (default: three repeats each of SATA mixed,
NVMe Gen4 mixed, NVMe Gen5 mixed, fast mixed, fast QD4 and fast QD8). A selected `nvme5-stripes` or `sata-stripes` scenario runs the
existing mixed-QD32 multi-target N=1/2/4 experiment. `fast-stripes-w4` and
`fast-stripes-w8` run the same independent-target experiment with sustained
WRITE-only QD4 or QD8, respectively, as described below. It prints compact development tables covering useful READ/WRITE, lower WRITE
bytes ratio and requests, READ/WRITE p99, windows, deadline and idle-bound
closes, accepted-work lower idle, lower-WRITE service and its EWMA, and keeps
detailed telemetry in `build/tests/fast-test/latest.json`. `SCENARIOS=` and `REPEAT=`
select scenarios and repeats. Every emulated scenario must use the production
delta64 + `DELTA64_SHUF8` byte-plane shuffle (byte shuffle) + LZ4
stack. Delta64-off benchmark arms are retired and must not be added to
`make test`, `make fast_test`, report plots, or performance history.

`make fast_test RESUME=1` may reuse a successful native/replay stage from a
private checkpoint under `build/tests/fast-test/resume/`. This cache is
separate from the fresh nonce-bound `development-evidence.json`; every
invocation replaces that admission record with its current HEAD, dirty state
and nonce. The product build always runs so embedded source provenance is
refreshed, and the environment-dependent loaded preflight always runs again.
Native/replay contracts may be skipped only when the working-tree content
fingerprint for their kernel production sources, native build definitions,
replay inputs and fast-test runner, the host/compiler identity, and hashes of
every required native test artifact match a previously completed PASS. Changes
to unrelated userspace sources, documentation or native tests that `fast_test`
does not execute need not invalidate that cache; a change to any fingerprinted
input, build environment or artifact does.
Missing, malformed, unreadable or non-private checkpoint state is ignored and
causes the required checks to run normally. The first invocation after this
resume implementation has no matching checkpoint and therefore runs the
native/replay stage once. Benchmark pairs always run fresh; an interrupted
benchmark reruns its selected pairs on resume.
An invocation without `RESUME=1` invalidates a matching old PASS before it
starts a fresh native/replay run, so a newly observed failure cannot leave that
same checkpoint available for a later resume.

Checkpoint data is bounded, mode 0600 inside a mode 0700 directory, and
atomically replaced. The physical development helper requests `RESUME=1` to
avoid repeating valid native/replay work after unrelated main-branch advances,
while its own source, artifact, nonce and final pre-mutation checks remain
mandatory. Resume never changes `make test`, qualifies a source, or lets
cached environment-dependent preflight satisfy a new invocation.
Rootless regression must prove an exact matching checkpoint skips only the
native/replay stage while refreshing the product build and loaded preflight;
input, host or artifact drift must rerun native checks, and a forced fresh run
must invalidate its matching old PASS before those checks begin.

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
these repeated development pairs decide only which candidate deserves the full
owner matrix; they do not create qualification evidence or paired confidence
intervals.

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
retain byte-exact timed READs and complete final-image verification. For both
Python-threaded wave and persistent lanes, all measured worker completions must
precede a checked final fsync of the opened target, within the timed interval
and before the final lower-I/O/CPU snapshots or a PASS result. A failed drain
must identify the candidate/mixed phase, OS failure reason, expected versus
observed measured WRITE byte counts and the failed final-drain oracle; final
byte readback cannot replace it. Timed short I/O must identify READ versus
WRITE and expected versus observed byte counts; a completed-length READ with
wrong content is a byte-oracle mismatch, not a drain failure. A worker failure
before the persistent start gate opens must abort barriers to release waiting
peers, join them, and preserve the first non-barrier worker error rather than
masking it with a racing or generic barrier failure. After that gate opens,
workers must preserve the original I/O failure without aborting the released
barrier generation and masking it as `BrokenBarrierError`.
The native-C engine retains its independently checked final fsync.
The checked-in rootless replay suite must exercise the actual Python CLI
regular-file replay for QD waves, persistent WRITE and persistent mixed lanes:
prove all workers complete before exactly one measured final fsync after prefill,
and that the measured end timestamp follows the successful drain. Injected
final-fsync EIO must block PASS and report publication, preserve the original
path-redacted OS reason, and report expected versus observed measured WRITE
bytes with the candidate/mixed phase. Short worker completion must fail before
final drain; a byte-oracle mismatch after a successful drain must remain
distinguishable from a syscall drain failure. A sampler cleanup error must fail
an otherwise clean replay but never hide a primary worker or drain error.
On a failed worker, all submitted sibling jobs must be joined before their
memoryview-backed I/O buffers are released; cleanup must not replace the
original short-I/O failure with an exported-buffer error.
These synthetic cases must not change the frozen trace cohorts, native helper,
source-bound hashes or loaded acceptance policy.
Results must identify the replay mode and remain outside the existing history series.
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

Packaging rootless test fixtures use a 60-second bounded default transaction
watchdog after two different ordinary package test cases timed out on separate
slower hosts at the prior 15-second limit. Explicit short fault-injection
timeouts still take precedence; kill-and-reap remains separately bounded.
An expired watchdog is not by itself proof that the package is defective:
authenticated console diagnostics must distinguish a still-running command
from a package process that exited while a descendant retained output pipes,
preserving the original exit, bounded budget and recovery-not-assessed state.


A complete run includes:

1. Product/module/userspace/helper build.
2. Direct production-C native tests plus source, build-interface, report and packaging contracts. Harness scripts `tests/tools/deploy-nullblk.sh`, `packaging/package-dkms.sh`, and `tests/runtime/native/package-dkms-test.py` must retain executable mode (`0755`) so bounded runner contracts and direct invocation invariants hold. Treat a checked-in mode regression as a source failure and restore its executable Git tree bit; do not weaken the Make-interface contract to hide it. Any content edit to these harnesses must preserve the existing executable tree mode.
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

The official reporter must treat recognized loaded FAIL/BLOCKED diagnostics and
build-stage Secure Boot signing BLOCKED evidence as non-PASS even if a child
returns zero. Preserve the actual child status separately when it differs from
the fail-closed stage exit, and attribute the recognized diagnostic to that
stage before considering missing benchmark evidence. Synthetic earlier FAIL
text in a successful rootless aggregate is not independently a failed stage.
Loaded progress may show a fixed failure category but must not echo raw child
stderr. Direct nested unittest diagnostics must redact absolute host paths;
a final authoritative rootless marker must not inherit earlier suite or later
nested error detail. Loaded diagnostics are scoped to the most recent recognized
phase boundary so expected FAIL text from a completed phase cannot be imported.
Every numeric `FAIL: test exit <status>; safe teardown attempted` epilogue is
secondary to the preceding specific failure, and the terminal loaded-kernel-debug
FAIL marker owns the loaded-kernel-debug evidence phase. Keep
incomplete/unexecuted stages non-PASS, retain the first causal exit through
report-write and cleanup errors, and bind publication to `tested_commit_sha`
rather than treating a report-only commit as a retest.


### Mandatory self-contained `make test` failure reports

A report that requires the owner to run a separate Python unittest, grep a
private log, or manually extract JSON counters to identify the first actionable
cause is incomplete. Treat that as a **reporting bug** and fix the reporting
path in the same change as the underlying defect; add a rootless regression
which exercises the complete official failure-console path. The developer
must not repeatedly ask for new ad-hoc diagnostic commands as bugs move between
hosts or phases. The automatic console must identify the authenticated first
failing stage, source-controlled test/subtest, safe file/line, error class,
bounded numeric mismatch or counter evidence, and the next safe action when
these facts exist. Child errors after the first failure and teardown diagnostics
cannot take precedence. A known cause may be printed only from a validated,
source-bound finite grammar; do not echo raw traceback text, child output,
credentials, host identifiers or absolute paths.

Nested unittest subprocesses must retain their stderr privately but promote
their authenticated inner test name, failure category and safely parsed
integer comparison into the outer `make test` result automatically. If the
inner cause cannot be authenticated, print a specific cause-unavailable notice
and retain the private log rather than inventing a test identity. Failure-only
private JSON snapshots collect measured rounds for READ coalescing, the
physical-trial verdict, and publication refusal details without re-running
any device test. Their 0600 paths must be printed; they must never qualify
the source or be uploaded to Git without the owner's explicit decision.

For an official loaded-stage failure, retain the stage's bounded merged child
output automatically in a mode-0600 file under `build/tests/`, bound to the
tested source SHA and fixed stage name. The console must print only its
repository-relative path and mode; never copy the child transcript or its
private path into `test_results.json`. Keep the original stage exit and first
failure authoritative if evidence allocation or fsync fails. Loaded phase
attribution must recognize `START_LOADED_OWNED_RAM_RECOVERY` as interrupted
owned-RAM recovery, rather than inheriting the preceding shared fixture phase.

Before compiling or running privileged qualification, inspect both index and
worktree for modified **tracked** source on local `main`, excluding only the
generated `test_results.json`. A dirty or unverifiable source blocks the
official run before the expensive stages, lists bounded validated
repository-relative changed paths, records `BLOCKED` and leaves all five
stages `NOT RUN`. Leave owner modifications untouched; never stash, reset or
discard them automatically. A generated report may be dirty without blocking.
A later source change after preflight must still fail the publication/physical
source-identity checks. Tests must prove this fast refusal, nested inner
failure attribution, privacy, first-cause ordering and unchanged gates.
No troubleshooting fix is complete merely because a separate direct command
reveals the cause. Synthetic unified rootless-stream fixtures must provide an
explicit finite source-controlled phase allowlist for their synthetic markers
and verify PASS and first-failure rows, the original exit, and a single header.
Keep a separate test for parsing actual declared source phases; a change in
source lookup must not silently remove rows from a synthetic display contract.
Synthetic test assertion failures must include bounded fixture-only captured
output so the cause is available in the official first-error report.
The isolated Make-interface incremental-build fixture may
override the checkout preflight only in its copied synthetic runner, because
that fixture deliberately edits tracked fake sources to check dirty build
provenance. This exemption must never reach the real `make test` command.

The ordinary loaded RAM preflight must distinguish the exact
`swapz-demo-physical-` development mapper name/UUID shape from its own
`swapz-demo-` RAM-test mapping. A matching name and UUID are read-only
classification evidence, **not** creation authority. Emit
`physical_trial_mapper_present` with a safe next step to inspect root-owned
same-boot physical state; retain the mapper/module and never auto-remove,
`swapoff`, reformat or adopt a physical mapper from the RAM preflight.
Malformed tokens and mismatched UUIDs remain fail-closed stale-token refusals.
Rootless regressions execute the exact admission branch with synthetic
`dmsetup` output for the valid physical shape, forged/malformed physical
shapes and valid RAM mapping, and prove zero real device operations.

The pre-consent Git gate must classify a dirty local checkout using the
existing physical helper's bounded source-owned classification
(`tracked_source`, `generated_report`, `untracked`) rather than returning
an undifferentiated `local_checkout_changed`. Report local branch and
tracking-ref mismatches as separate finite reasons before any consent or
physical action. These diagnostics cannot exempt a generated report from
physical admission or change the privileged helper's independent late gate;
print no arbitrary Git output, host paths or repository identities.
Rootless tests cover the finite reasons and maintain consent refusal.
The child must send its already-classified first source-refusal reason over
the private, captured stderr channel as one fixed
`PHYSICAL_ALGORITHM_SOURCE_ADMISSION` marker. The official runner may promote
only one exactly validated finite marker into
`algorithm_real_swap.reason` and the identity-free
`algorithm_real_swap.diagnostic` object of the *same* source-bound
`test_results.json`. Retain `overall=NOT_RUN`, exit 2, and all original
recovery and consent gates; an absent, duplicate, malformed or privately
expanded marker remains untrusted and must not reach stdout or publication.
Rootless tests must verify the exact official report path, the first
pre-consent refusal, and private stderr non-disclosure.

When the optional development physical swap trial follows five passing RAM
stages, its root-owned anonymous-pageout oracle must automatically collect
bounded read-only host reclaim evidence from `/proc/vmstat` and
`/sys/module/zswap/parameters/enabled` at the first missing backing-I/O
proof. Record the independent exact-mapper Used KiB and lower WRITE bytes,
the first missing gate (`mapper_usage` or `lower_write`), zswap enablement
when available, and only the host-global deltas for `pswpout`, `pswpin`,
`zswpout`, and `zswpwb`. Missing kernel counters remain null/unknown;
host-global counters are diagnostic context and never sufficient to certify
mapper backing. The official `make test` captures privileged stderr in an
auto-deleting private temporary file, promotes only one strictly parsed,
bounded, identity-free `PHYSICAL_ALGORITHM_DEBUG` record into the public
`algorithm_real_swap.diagnostic` JSON field, prints the authenticated first
failure and a safe next step, and preserves the original exit and recovery
outcome. Untrusted stdout/stderr, paths, hardware IDs or arbitrary helper
JSON must never enter the published report. Rootless tests must reject
duplicates, malformed/oversized records, unknown fields, invalid counters
and fake successful backing. Keep the official-run test fixture below the
Python compiler's static nested-context limit by combining independent mock
contexts; a regression must reach the reporter rather than fail at import.
Synthetic five-PASS stage fixtures must still seed each required benchmark
verdict read by the official runner (as NOT_RUN when no telemetry is supplied),
so a rootless test exercises the physical-report branch rather than failing on
a missing fixture-only benchmark key.
This diagnostic path must never change swap admission, force additional swap,
or replace the actual recovered-state checks.

When the optional development physical swap trial follows five passing RAM
stages, check the canonical remote source against the exact nonce-bound
RAM evidence **before asking for device consent**. Reuse the root helper's
report-only Git ancestry validation rather than comparing HEAD alone:
an authenticated report-only advance is allowed, but a new source commit,
an unstable remote, mismatched local tracking ref, or unverifiable evidence
must refuse the trial. Print an explicit finite, path-free
`PHYSICAL_ALGORITHM_REAL_SWAP=BLOCKED reason=... phase=before_consent`
marker plus a safe source-sync and exact-source rerun step. Never prompt the
owner to authorize swap mutation for a source already known to be invalid.
The authoritative privileged helper must independently re-validate canonical
source and all physical admission state just before any new swapoff, mapper
operation or device write. This early check is fail-only diagnostics, not
a waiver of the late protection; do not change the successful trial's
protocol or turn a virtual device into physical qualification. Rootless
controls must prove a concurrent source advance blocks before consent
and that report-only advances still reach the authoritative later gate.

The fast READ coalescing A/B gate retains every mandatory same-source merge-on
round, not just the earliest failure. On a zero-merge sequential round,
`make test` must automatically print bounded per-round sequential and
seeded-random kernel counters for successful merges, parallel batches,
executed adjacent pairs, gap/cache/noncontiguous-slot skips, and 3+-extent
candidate chains. Those counters are source-bound aggregate measurements,
not raw storage geometry or device paths. A positive gap-skip count means
the required missing READ ranges could not be merged into an exact contiguous
span; it does not identify whether placement or cache residency caused that
geometry. Keep zero-extra-block and every-round execution gates strict:
skipped candidates or successes from other rounds never become a PASS.
Rootless regressions exercise the official failed-stage console, verify its
first-cause output and guard private data. Malformed or non-integer counters are printed
as `counters=unavailable`, never interpolated from raw child fields.
The owner must not need separate JSON extraction commands to see the
failed rounds.

### Native/rootless fail-only subprocess attribution

The private `tests/tools/test-rootless.sh` runner must keep the exact registered
suite invocations and their sequential order, including package transactions.
Each unexpected child failure is attributed to its source-controlled suite
pathname or static shell-check phase, with the **original** numeric exit status,
a phase elapsed wall-clock count, total rootless-stage elapsed wall-clock count,
and a source line for directly failing shell assertions. The first nonzero
command wins: later checks must not run or replace its reason. Bash's built-in
`SECONDS` is sufficient for fail-only wall-time attribution; do not spawn
`date`, `time` or `tee` for every passing test, add PASS chatter, adjust frozen
timeouts, or reinterpret a long-running phase as a hang. Exit 124 alone is
ambiguous between a watchdog timeout and a child returning 124, and a TERM
signal cannot prove why termination occurred.

On failure only, retain one bounded diagnostic containing safe phase/status/time
fields and a next inspection step in a freshly allocated private 0700 directory
under `build/tests`, with a 0600 regular log file. The failure marker may give
its **repository-relative** log location but must never print root checkout
paths, arbitrary child stderr, credentials, payload bytes, device identities,
UUIDs or `BASH_COMMAND`. The original subprocess output remains in the
caller's privately captured official-stage output for finding the first
`FAIL:`/`ERROR:` unittest; do not copy arbitrary child output into
publishable reports. Only allowlisted source-controlled phase text and fixed
reason classes may be promoted from a private capture into `FAIL:`, `Failed
during:`, or `Reason:` markers. A failing status must survive diagnostic write
errors and EXIT/ERR/signal traps without a duplicate marker.

The initial native Make stage, the long package unittest, and the primary
real-swap native contract suite are the only rootless suites that may keep a
transient private stderr copy while they run. One relay process may preserve stderr
byte-for-byte into a mode-0600 file inside the mode-0700 failure directory; do
not add a relay process to every passing suite. On PASS the file and directory
are removed immediately. On failure, retain at most 64 KiB from the selected
execution-first detailed block plus at most 188 KiB of trailing stderr, followed
by bounded attribution metadata. The selected-block excerpt keeps both a bounded
prefix and suffix so an unusually deep traceback cannot push its terminal
assertion or exception beyond the retained prefix. This fits the existing
256-KiB capture budget and keeps the first traceback even when unrelated
progress stderr displaces it from the tail. The excerpt matcher must recognize
both the package and primary-real-swap unittest classes; matching only one class
can discard the other suite's first assertion before the bounded private log is
finalized. For the initial `make -C tests test` stage, leave stdout unchanged
and relay only stderr. Only a matching `swapz-primary-late-race-test.py`
traceback, generated-C compile assertion, compiler `error:` line, and
failed `test-userspace` Make target may authenticate the nested failure.
The first observed Make target failure owns the classification: if another
target has already emitted a real `make: *** ... Error` record, a later
parallel late-race failure must not replace it. The public marker retains the
Make phase, the original Make exit 2, and fixed
`test=swapz-primary-late-race-test.py subtest=compile
reason=native_compile`; the outer CI envelope maps this authenticated reason
to `NATIVE_COMPILE`. The compiler declaration and arbitrary source paths stay
only in the private diagnostic. Oversized captures must retain a bounded
late-race traceback excerpt plus the first compiler `error:` line even when
more than the normal transcript tail follows from other parallel jobs.
A prior passing suite's expected `FAIL:` text cannot authenticate a later
failing suite. The outer `native-rootless` CI diagnostic must retain any
validated relative private-log pointer as `rootless_private_log` even when a
first nested Make error becomes `first_error`; `first_error` must not copy
private source paths or traceback text. A missing or invalid final marker
must not inherit an earlier marker's test identity or private-log pointer.
A generic nested Make failure may disclose only the first
source-controlled `tests/suites/Makefile` target from its own `make: ***` error
as a `subtest` (for example, `test-mapping`). The reported Makefile line must
resolve to a recipe line owned by that exact target in the source-controlled
Makefile; a mismatched, stale or out-of-range line is unauthenticated. The
outer CI parser must repeat that recipe-line ownership check before promoting a
raw Make record to `first_error`; matching only the authenticated marker's
target name is insufficient. A malformed final rootless marker also suppresses
earlier raw unittest and Make-shaped attribution rather than falling back to
untrusted child text. This is a target-level phase hint, not proof of an
individual executable, Python traceback
or native assertion category. A silent or unrecognized failure keeps
`subtest=unavailable`. Incomplete relays or absent matching evidence retain
`test=unavailable reason=nonzero_exit`. Python `unittest` preserves execution
order in verbose `... FAIL`/`... ERROR`
progress records but groups detailed `ERROR:` blocks ahead of `FAIL:` blocks in
its summary. Classification must therefore bind the first failed progress record
to its matching detailed traceback; a later teardown error must not win merely
because its detailed block is printed first. The progress and detailed method
must agree and belong to the currently executing source-controlled suite
class; expected negative-test output from another class cannot claim the
active phase. A progress-only line without a matching detailed block must
remain unauthenticated rather than claiming a prior fixture's test identity.
Private progress/detail matching must accept source-controlled unittest
`phase=` labels containing underscores (for example `detached_signature`)
so their execution-order record cannot be skipped in favor of a later ERROR.
The existing public rootless-marker subtest grammar remains lowercase
alphanumeric plus hyphen; an authenticated underscore-bearing phase therefore
stays private and is reported publicly as `subtest=unavailable`, without
losing the authenticated test name or failure kind.
 For PackageLifecycle, PrimaryRealSwapContracts and
SourceAdmissionPeerOwnership, the private progress matcher must also accept a
bounded arbitrary unittest subtest context so additional keys such as
`case=` or `field=` cannot hide the execution-first record. Arbitrary
context remains private; only an exact single `phase=` context may supply the
existing public subtest token. Synthetic controls without progress
records may use the first detailed block as a compatibility fallback. Retain the
allowlisted execution-first unittest name and first assertion or exception
privately. The official native-stage diagnostic binds unittest identity to the failing
rootless marker: when that marker carries an allowlisted test name, that name
wins over earlier suite output and later teardown; when it carries
`test=unavailable`, earlier transcript `FAIL:`/`ERROR:` lines must not be
guessed as the cause. A directly invoked, unwrapped unittest may still use its
first detailed failure block. A generic rootless
`reason=nonzero_exit` for `test-report-test.py` does not authenticate an
assertion even if earlier stderr includes that phase name or an apparent
traceback. Only the separately invoked unittest CI job may attribute its own
direct assertion; it cannot authenticate rootless child output. The official
stage record keeps the
source-controlled rootless phase in `failed_phase` (the basename for a Python
suite), not as an absolute or repository-prefixed path inside `diagnostic`.
For a complete final marker whose exit matches the actual child, its bounded
public `diagnostic` must preserve the causal summary and authenticated
`child_exit`, `reason`, `subtest`, `test` and relative private `log` pointer;
tests must not demand an obsolete bare summary or discard those fields.
Adversarial official-stage fixtures must verify first-failure precedence when
a later unittest or cleanup failure appears, without exposing later failure
identity, private traceback text or absolute paths. An unauthenticated
late-race compile claim must suppress its test and subtest identity; malformed
child exits or unsafe log pointers cannot authenticate a rootless marker.
The final rootless failure prefix suppresses cross-suite unittest guessing and
clears earlier marker identity; only its complete sanitized grammar may contribute classified test identity. The public marker may expose only allowlisted phase/test/subtest tokens and
classify that first private failure as `native_compile`,
`unittest_timeout`, `unittest_assertion`, `unittest_error`, or the
generic nonzero reason. Exit 124 remains ambiguous unless that first private
unittest traceback itself contains `subprocess.TimeoutExpired`. Successful
stdout/stderr bytes and exit status remain unchanged and no failure log is
retained. A relay or relay-cleanup failure after a passing child is a harness
failure (status 1, `stderr_relay_failure` or
`stderr_relay_cleanup_failure`); after a failed child, its original status
takes precedence. If cleanup fails before unlinking the capture, reuse that
surviving regular file as the sole pointed private diagnostic instead of
orphaning it and allocating a second log. A capture from a nonzero relay is
diagnostic-only and must not classify the child as a unittest assertion, error
or timeout because completeness is unknown. After the tested child exits, the
relay must retain an unused output-pipe descriptor through the owned tee
process and receive a bounded EOF probe on that pipe before wait; do not
redirect the runner's stderr while closing its parent-side descriptors. An
inherited input writer or stalled relay cannot indefinitely hide the first
child exit. Kill an incomplete owned relay, never classify its partial stderr,
but retain a surviving regular private capture when the tested child already
failed so the first diagnostic is not discarded merely because relay completion
failed. Preserve the child status even if the relay or its cleanup fails. This
relay-bound timeout is not evidence of a child deadline or an exit-124 watchdog.
Relay diagnostics may not print
private filesystem paths. Failure-log allocation must not follow a symlinked
build/tests directory.
The private `tests/runtime/native/rootless-attribution-test.py` regression runs
before package transactions in the existing rootless path, using the real
initial Make, package and primary-real-swap stage Bash functions with bounded synthetic stderr,
temporary storage,
and a genuine Python `subprocess.TimeoutExpired`. It must also cover
first-failure ordering, oversized capture, no-log storage, cleanup failures,
and privacy of public markers. Explicit shell exits and failing shell
assertions remain part of the general rootless attribution contract.
Shell snippets that extract and invoke the classifier must initialize
`rootless_phase` to the registered suite matching their synthetic unittest
class; this preserves the active-suite binding under `set -u`.
A direct classifier fixture extracting the real rootless runner must account
for its single source-controlled initial `ROOTLESS_PHASE_PROGRESS` stdout
record, then match the sanitized unittest identity exactly; neither output
may include private exception bytes, paths, or an invented first failure.
Synthetic marker mutations must preserve token boundaries; changing `test=`
must not also alter the suffix of `subtest=` or invalidate the marker grammar.
These regressions do not substitute for the loaded checks in either public
qualification tier or physical admission.

For direct rootless phases whose stderr was not pre-captured, the official
reporter may append bounded first-error context from its already captured
merged stage output to Bash's **existing failure-only** `diagnostic.log`.
Do not add a relay process to passing suites, create a second log, or change
successful output. Require the last complete source-controlled Bash rootless
marker to match the original child exit and an owned mode-0700 directory
holding a regular, single-link, mode-0600 attribution-only log; reject symlinks,
unsafe permissions and pre-captured logs. The entire artifact, including Bash
attribution, must remain within 256 KiB. Compaction must reserve space for the
final attribution trailer even when captured stderr is below 256 KiB. Class-specific first-failure matching
is limited to source classes in `tmp-cleanup-test.py`, `test-report-test.py`
and `primary-lifecycle-audit-test.py`; other direct phases receive a clearly
labeled contextual tail only, never an invented test identity. A silent failure
cannot claim a matched traceback. An earlier rootless marker superseded by a
later marker cannot authenticate the earlier failure. The public report retains
only source-controlled phase, original exit, fixed reason, sanitized log pointer
and the fixed numeric-errno/cleanup fields defined below;
`subtest=unavailable test=unavailable` remains unless Bash itself authenticates
nested identity. The official stage reporter must preserve the
full relative `log=` pointer for every complete, status-matched final Bash
marker, including `line=unavailable`; a malformed or exit-mismatched marker
cannot borrow an earlier suite's apparent test identity. Nested Make exits and
private errno text are not independently authenticated. Secondary diagnostic
failures must never replace the original child failure. Read retained evidence
locally, never publish it. On a failed `make test`, the console may also show
the first unittest name, basename/line and strictly allowlisted assertion
expectations (bounded phase/ownership/status markers, short values and fixed
failure categories). Source-matched package crash subtests additionally
report only the finite install/uninstall action and durable checkpoint phase,
and name subprocess.TimeoutExpired by class without showing its command.
The SIGKILL lifecycle audit must run its setup install through the supported
ordinary package invocation watchdog, without an unsupported per-call timeout
argument. A setup refusal must identify the crash-audit setup phase, finite
install/uninstall action, intended checkpoint and original child exit before
the private stderr. Its isolated committed-install recovery case
may allow up to 90 seconds for the durable crash checkpoint on slow USB-root
hosts; it must still prove SIGKILL, lock reacquisition, recovered exact
package bytes and clean reentry. The general package operation watchdog
remains independently bounded at 60 seconds, and all other crash checkpoints
retain the 30-second default. An imported PackageInvocationTimeout must expose its
verified class and only authenticated, path-free original operation, elapsed
time, finite budget, first cause and process disposition on failure.
The nullblk-identity-test.sh fixture must emit bounded source-owned
case/line/reason/status evidence on both assertion and unexpected-command
failures. The public make-test reporter validates the case against the
current fixture source, and can display only its finite native configfs
proof phase/status. Raw device identities, sandbox paths, exception messages
and child stderr remain private. For the source-controlled `test-lower-io`
Make target, the seven native C fixtures run in their existing order and
retain the original failing executable's exit code. On failure only, the
native recipe emits a fixed `FAIL: native test-lower-io binary=... exit=...`
marker. The official `make test` reporter authenticates it against the
source target's prerequisites, its nested Make error and the final rootless
phase before printing the executable and a source-bounded .c assertion
location when present. The recipe uses Make-escaped `$$native_test`,
`$$native_exit_status` and `$$?` so its loop variables and original status
reach the shell unchanged. A rootless regression runs the real recipe with
disposable fake executables, verifies first-failure stop/order and original
status, and catches lost Make dollar-sign escaping. Arbitrary C assertion operands, host paths and
device data remain private. Keep nullblk-identity-test.sh executable in Git.
Authenticated PhysicalSwapProbeTests recovery failures additionally show the
deepest source-controlled physical-swap-probe.py frame (basename and line),
physical_swap_probe.ProbeError class, and allowlisted immutable binding field.
They never expose mismatching state values, private host paths or unrecognized
field names. Source-owned physical probe failures can retain an authenticated
unittest traceback across a bounded 32-KiB post-footer diagnostics trailer,
rather than discarding all cause detail after 2 KiB of private smoke paths.
Only an exact physical-probe rootless failure marker and a matching
PhysicalSwapProbeTests class may use that wider window; unrelated phases
retain the conservative 2-KiB limit. Two allowlisted restoration-state
constants may appear as explicit observed/expected values; arbitrary assertion
operands remain private. These clauses describe the retired
`physical-swap-probe.py` compatibility fixture only: its synthetic historical
state/results records must use the same immutable run_id, and its old
restoration simulation must reread the fixture state after cleanup rather than
a stale dictionary alias. The interrupted-fsync negative fixture must not
invent persistence. None of this historical probe state authorizes current
lifecycle recovery, raw-header backup/restore or persistent swapz metadata.
The source-contract guard checks that the physical probe is absent from
executable make-test commands, without forbidding its filename in
observational diagnostics.
Comparisons of two exact fixed sanitized markers (for example, a withheld
unittest identity versus a private-exception omission marker) show both
observed and expected fixed states without exposing arbitrary child text.
Focused rootless regressions exercise the actual operator console for both
failure types and require private operands to stay withheld. The raw actual assertion value, paths, device identities,
private stderr and full traceback remain only in the local private log; no
additional detail is printed on a passing run or published in the JSON report.
For an authenticated first `PackageLifecycle` ERROR whose traceback carries
`PackageInvocationTimeout: SWAPZ_PACKAGE_TEST_TIMEOUT`, the rootless runner
classifies the known bounded package-fixture watchdog as `unittest_timeout`
rather than an unspecified unittest error. On failure, the official `make test`
console prints the first matching package watchdog's fixed action, codec,
elapsed/budget seconds, budget reason and owned-process disposition, only
after matching the authenticated source-controlled test marker and the exact
finite-domain, path-free exception envelope. It does not copy a raw exception,
a host path, subsequent test errors, arbitrary fixture text or the private
log into the console or JSON, and it does not relax any watchdog or gate.
The standalone rootless stderr relay still preserves private child bytes
unchanged for its bounded capture; public privacy assertions apply to the
fixed Bash marker fields and the official `make test` summary, not the
unsanitized intermediate relay transcript. When a rootless attribution
regression runs successive failing scenarios in the same isolated fixture,
it must inspect the first retained diagnostic before removing only that
fixture-owned regular log and its empty directory. The next scenario's
single-log assertion must not count the preceding scenario's evidence;
production failure retention and first-failure ordering remain unchanged.

### Native CI failure evidence contract

The private project-goal wrapper in `tests/tools/product_goals.py` is
observational and fail-only; it must not alter suite discovery, execution
order, qualification severity or either source-bound public Make tier.
On a failing exact-SHA command, its existing `swapz-ci-diagnostic-v1` record
retains the public suite and artifact name, actual wrapper `exit_code`,
first causal `first_error`, category and reason, and now also explicitly
records the source-controlled `phase`, failing unittest or nested test name,
`expected_contract` and sanitized `observed` diagnostic. A validated
rootless failure marker supplies its allowlisted execution-first `test`, may
supply a separate `child_exit_code` and `rootless_reason`, and retains the
repository-relative private-log pointer when available; it must **never**
overwrite the outer process status.
Only the `native-rootless` wrapper may promote that marker. Its phase is the
source-controlled basename emitted by `test-rootless.sh`: allow ordinary
letters, digits, spaces, dot, underscore, hyphen and the colon used by C-syntax
phases, but never a path separator. Keep the last valid marker because the
runner emits its authoritative summary after arbitrary child output. Current fixed reason classes include `native_compile`, the unittest reasons,
timeout-or-exit-124, signal-or-child-exit, received INT/TERM, and stderr
relay/relay-cleanup failure. `native_compile` is accepted only for the exact
Make phase, `subtest=compile`, `test=swapz-primary-late-race-test.py`, and
child exit 2. A late-race filename combined with any other reason, subtest,
phase, or child status is unauthenticated: outer reporters must suppress the
test and subtest identity, keep the validated outer phase, use a generic unknown
category even when the marker claims timeout, signal or runner interruption,
and must not borrow earlier Make/compiler diagnostics or the private compiler
declaration.

An OSError at child launch retains its original `launch_errno` and sanitized
OS error text without publishing the executable or command string. Negative
return codes identify a real direct-child signal. A rootless
`signal_or_child_exit` marker is **not** cancellation evidence: shell
128+signal-style status and an explicit child exit are indistinguishable.
Likewise, exit 124 alone cannot establish a watchdog timeout. A runner marker
that explicitly says it received INT/TERM may report interruption while still
stating that the interruption's origin is not proven. An authenticated
`unittest_timeout` marker is a failed runtime-test contract: preserve its
original child status and safe private-log pointer, and do not relabel it as
cancellation, a proven watchdog, an infrastructure outage, or successful
cleanup. Generic exit 124 retains the existing execution/infrastructure
classification while its reason must state that watchdog origin is unproven.
Bare 130/143 and direct-child INT/TERM retain the existing cancellation
classification; `signal_or_child_exit` remains unknown because shell
128+signal-style status and explicit child exit are indistinguishable.

For validated native-rootless output, the runner's execution-first marker owns
unittest identity because Python may print a later `ERROR:` detail before an
earlier `FAIL:` detail. Later teardown, cleanup, parser exceptions, and
make-summary errors must not replace that identity or donate a later exception.
For ordinary non-rootless unittest output without such a marker, the first
detailed failing block remains the fallback diagnostic. Genuine first native
compiler diagnostics are preserved for generic compile phases even when an
outer rootless marker follows. For the authenticated generated-C late-race
fixture, the public envelope uses only the fixed `native_compile` marker and
private-log pointer; it must not publish the compiler declaration or source
path. For a marker-only rootless failure, an unrelated earlier expected
`FAIL:`/`BLOCKED:` from a passing suite must not become the cause. A generic nonzero phase may retain a diagnostic only when it
is tied to that source-controlled phase (or is the first native compiler error
of its compile phase); otherwise the safe phase/reason/child-status marker is
the observed diagnostic rather than guessing from earlier output. Relay and
relay-cleanup failure reasons are harness/infrastructure failures and never
replace an earlier failing child's status.

A validated rootless `bash syntax <script-basename>` marker with
`subtest=unavailable`, `test=unavailable`, `reason=nonzero_exit` and
original child exit 2 identifies the failed source-controlled `bash -n` check
as `SOURCE_CONTRACT`, with an explicit required successful parse and observed
failing command status. The basename may be either a `.sh` script or an
extensionless shell source registered in the producer syntax loop. This does
not prove the precise Bash parser message; that detail stays in the referenced
private log. Missing or malformed marker fields, unexpected test/subtest
identity, a different child exit/reason, or unrelated earlier
`FAIL:`/`BLOCKED:` output cannot be promoted to that shell-syntax
classification. A phase-linked producer permission `BLOCKED:` remains
distinguishable as `HOST_PERMISSION`;
unittest assertions and relay/runner failures retain their existing separate
classifications. None of these labels changes test severity or qualification.

The existing v1 CI diagnostic additionally gives the first observed exit
(`first_exit_code`), a numeric original `first_errno` or null when unknown,
and `cleanup_disposition`. The authoritative rootless `FAIL:` marker grammar
remains unchanged for report-producer compatibility. Its immediately following
fixed `Reason:` line may append only `first_errno=<number|unavailable>` and
`cleanup=<fixed-state>`; the CI parser may consume those fields only when
exit, reason, subtest and safe relative log repeat the final authenticated
marker exactly. A nested errno may be promoted only from the matched first
unittest detailed block, never from arbitrary boundary or cleanup text. Outside
that authenticated rootless detail, `first_errno` may come only from a genuine
Python OSError-family exception line or the wrapper's own fixed
`INFRASTRUCTURE: cannot start test: errno=...` launch diagnostic; a bare
`errno=N` in assertion or child text is not original-errno evidence. An
unverified child cleanup remains explicitly
`not_independently_verified`; relay-only failures may use fixed incomplete or
cleanup-failure labels but never assert successful child teardown. The existing
`expected_contract` and `observed` fields remain the public expected/actual
conditions. Redact structured child-supplied JSON only when it occupies an
explicit diagnostic value field (or the complete AssertionError payload), plus
token paths, UUID/PARTUUID, serial/WWN, campaign identifiers, device IDs, and
absolute host paths before promoting first-error text; do not infer protected
identities. Structured JSON embedded in a recognized exception line is also
private diagnostic payload and must be redacted. Do not rewrite
repository-controlled traceback source syntax merely because it contains
brackets or braces. Preserve ordinary numeric expected/actual
values because they are required causal diagnostics, not identity payloads. Keep
only the allowlisted source-contract and make-interface script basenames
visible after redacting their private containing root, so original source
contract failures retain their existing classification.
A captured logical line truncated by the bounded reader must retain the
fixed `[truncated]` witness even when unsafe child exception detail is
replaced by the sanitized `[private exception detail omitted]` placeholder.
The witness must never reinstate drained suffix bytes or cause private
tokens to enter public CI output or the retained failure log. Synthetic
byte-stream regression must verify both retention and redaction.
A hostile or malformed unittest heading sanitized to the fixed
`FAIL: unittest identity withheld` or `ERROR: unittest identity withheld`
is not by itself a classified causal error. When a subsequent exception
exists, its sanitized class and fixed omission marker supply the first cause
without restoring an untrusted test identity. A withheld heading alone
remains a generic UNKNOWN_FAILURE, never a proven runtime assertion; later
cleanup exceptions must not displace an earlier sanitized cause.
A standalone authenticated teardown failure remains attributable only when
no earlier classified cause was observed. The native
CI diagnostics tests must distinguish allowlisted numeric `expected=N
observed=N` assertions (preserve exact numbers and first-cause identity)
from arbitrary child-authored assertion/setup strings (retain the exception
class and private-detail omission marker only). The log-retention failure
fixture must likewise retain original exit and diagnostic errno without
printing the child's private assertion text.
If sanitized-log retention itself fails, the original test exit and cause are
still reported, while `log=unavailable` and the numeric diagnostic errno
describe that secondary evidence failure. All promoted fields use the existing
bounded sanitization and allowlisted rootless-marker syntax; do not promote
private local log contents, command strings, credentials, output payload bytes,
or unvalidated paths. Passing commands emit no extra transcript, retain no log
and incur no new subprocesses.

The Make-interface synthetic CI attribution fixtures must use canonical
fully-qualified Python unittest failure headings to authenticate a test
identity, and expect only the exception class plus the fixed private-detail
omission marker when a child supplies arbitrary assertion or setup text.
Expected negative REFUSED/BLOCKED fixture output must never become the first
cause of a later authenticated unittest failure. Synthetic Make Error 134
attribution must use the current source-controlled recipe line in
`tests/suites/Makefile`, not a hardcoded historical line number; an
unverified recipe line must continue to be refused.

The narrow synthetic `tests/tools/ci-failure-diagnostics-test.py` regression
covers native assertions, nested unittest/cleanup precedence, compilation
errors, timeout-or-exit-124 ambiguity, signal versus shell exit, rootless
child status, missing executables, redaction, unchanged artifact naming, and
log-retention failure without privileged, device, swap or kernel operations.
It is an internal focused fixture, not a new official qualification interface
or an additional workflow gate.

Package install, upgrade and uninstall must preserve primary recovery authority.
An exact already-installed identity may return as a no-op, but any package
mutation is BLOCKED while `primary-state.json` or a partition ownership marker
exists. This prevents a package transaction from replacing the qualified
control/module snapshots needed to reconcile an interrupted primary lifecycle.
The rootless package suite must exercise both durable-state and ownership-marker
refusals and prove the installed bytes remain unchanged.

The cross-component package SIGKILL-to-primary admission rehearsal must wait
up to the existing finite 90-second fixture maximum at **each** durable package
checkpoint (including `module-promoted`), not merely at `committed`.
The package fixture's shorter 30-second default can misclassify slow-storage
or competing rootless-worker delays as a lifecycle regression before the
checkpoint is reached. Expiry still FAILs; it cannot establish retained
transaction state, recover ownership, or turn an absent checkpoint into PASS.
The test must still verify the exact durable phase, untrappable SIGKILL,
reacquirable package lock, denial of both primary `prepare` and `start`,
and permission only for `stop`/`recover`. Its rootless contract checks the
90-second default and finite overrides without invoking real device actions.

The package admission suite must replace a pinned transaction directory with a
different directory on the same mount between descriptor and named-path
revalidation; compare inode, device, owner, type and mount identity and require
the substitution to fail before mutation. The primary prepare fixture must
inject global-lock close failure and verify that it emits a phase-specific
failure with no `PRIMARY_PREPARE=READY` marker. A successful prepare marker is
valid only after the outer mutation lock closes successfully.

Package mutation and every mutating primary command, including
`qualification-import` and `prepare/start/stop/recover`, must contend on the
exact same global `/run/lock/swapz/package.lock` before either side inspects
mutable package/lifecycle state. Primary holds that lock for the whole operation
and acquires its partition recovery lock only afterward. Native and
rootless tests must prove a second lock attempt returns
`EWOULDBLOCK`/`EAGAIN`, release permits a later holder, a held package lock
blocks package mutation without installing bytes, and source contracts bind the
C and shell lock paths. Native production-C policy coverage must additionally
start with an absent mutation-lock directory, prove the lifecycle helper creates
that exact directory, acquires/releases its lock, and can remove the private
fixture afterward; this models `/run` being cleared across reboot. The
owned-null_blk lifecycle rehearsal uses a private token-bound lock directory and
must not contend on the host production lock.

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

The codec envelope regression must construct at least one complete canonical
little-endian extent independently of the production builder and CRC helper,
then compare the writer's entire serialized extent, including cleared padding,
byte-for-byte. It must separately check metadata and payload CRC corruption,
exercise metadata-only structural and descriptor inspection through the documented
peek/descriptor APIs from an actual 4KiB allocation while the physical extent
class is 16KiB, reject CRC-valid metadata-aliasing
and out-of-extent payload offsets, and verify the 64-record capacity boundary.
Writer inputs must not overlap the exclusively owned builder extent. These
checks are native/sanitizer evidence; they do not replace live mapper testing.

The native production-engine prepare/complete boundary must use the actual
`swapz_engine_prepare_batched_run()` implementation with caller-owned,
bounded run bytes and transactions, not an independent simulation of the
codec gate. It must reject compressed payloads aliasing any part of the
builder-owned extent before their first CRC read, for ordinary and supplied-
prehash inputs alike. The source must be poisoned under native ASan where
possible without poisoning the initial header write. Left/right boundary
contact and disjoint sources are valid only when the full readable payload
stays outside that extent; a failed packed sibling must not cause even a
partial lower WRITE or authoritative publication. The test must inspect
errno, lower callbacks, map generations, abandoned/committed reservations,
paused transaction ownership, record identities and payload CRCs, and then
retry with independent bytes through the same scratch allocation. Cover
all compressed encodings, a prehashed success path, RAW publication and
DISCARD generation transitions, finite capacity, unsupported encoding,
invalid lengths and generation overflow. A dedicated failure diagnostic
must name engine phase and input category, relative offset/length,
expected/actual errno, and whether lower-write/publication counters changed;
never print payload bytes.

Only the compressed builder path has a validate-before-payload-hash contract.
RAW uses a separate direct-copy path; do not claim that a compressed codec
overlap check guards RAW memcpy. Before that copy, the exact production batched
engine must reject overlapping one-block RAW sources and destinations using
address-distance bounds (not pointer ordering); exactly adjacent one-block
sources remain valid. The rootless native regression must prove exact left and
right one-block contact succeeds, then exercise left and right partial overlap
plus exact alias. Under native ASan, poison a bounded subrange of each
overlapping source so rejection is proven before the copy reads or writes those
bytes. Every rejection must return -EINVAL with zero additional lower callback,
engine submitted-block credit, physical completion credit, caller committed-page
count or post-publication callback; preserve the prior generation and RAW CRC,
and quarantine the attempted reservation before retrying independent bytes from
a fresh range. Its failure diagnostic must retain the originating errno,
attempted transaction sequence/generation, retained and expected/observed
mapping, caller committed pages, submitted/completed counts, and retained or
quarantined reservation state without dumping payload bytes. Zero-page elision
and DISCARD are mapper or authority transitions rather than encoded append
records. An explicitly
compiled ASan-only broken-prehash control may intentionally hash a poisoned
overlapping input before engine validation, solely as an unsafe native
negative control, never against storage or in the default native suite.
This native evidence does not substitute for the loaded-kernel gate.


The transaction-publication native fixture must additionally use the exact
batched engine/authority paths for one finite mixed replacement at the
logical-generation limit: an existing RAW page becomes compressed, an existing
compressed page becomes RAW, and a previously unmapped compressed sibling
shares a run. The serialized fixture must explicitly enable the rotating
allocator before staging the batched run so batch pause owns the staged
reservations; segment-role registration order is not itself publication
authority. One prefix block must actually reach isolated test media before
the lower callback returns its original -EIO. While the immutable batch is
paused, staging and DISCARD must both return -EBUSY. A failed completion must
report zero committed pages, zero publication callbacks, exact submitted/
completed/abandoned/committed block counts, unchanged old generations and
liveness, byte-exact RAW and compressed-payload survivors, and an unreadable
newcomer. The unwritten media suffix must stay untouched. A successful retry
must reserve fresh blocks, publish each new representation exactly once, and
allow one final DISCARD without u32 generation wrap; subsequent WRITE/DISCARD
must fail -EOVERFLOW with no authority mutation. The fixture is serialized,
rootless production-C evidence, not a loaded-kernel fault-injection claim.
On a failing assertion, name the phase-correct operation and logical generation,
the reservation/publication phase, the original injected errno, expected errno,
captured actual errno and retained authority. Never report an expected or stale
errno as the actual result of a survivor read, DISCARD or rollover refusal.
Counter diagnostics must show exact expected/actual committed-page, lower-run,
sealing, publication, reservation-cursor, authority-reservation and engine
completion/success values; print no successful per-operation logs or private
page bytes.

Native tests compile the real `src/kernel/{codec,authority,engine}.c` where applicable. They cover codec integrity, authority publication, torn/short failure, overwrite generations, discard, zero-write representation, online packing, randomized authority, lower-run aggregation, flush/FUA accounting, retention/window policy and GC rotation/cost invariants. Source-body qualification must recognize the intentional `noinline` attribute on production helpers without relaxing symbol or return-type matching; stack-isolation annotations are part of the code under review, not a reason to make the helper invisible to source contracts. Multi-page upper DISCARD must run an allocation-free authority prevalidation before the first generation/refcount mutation. That prevalidation must model cumulative physical-liveness, mapped-page and GC-accounting decrements, validate each affected page's head-reachable page-list membership with reciprocal links and a bounded walk, reject detached cyclic list components, reject any orphan physical liveness in a closed segment that the range would make dead, and independently full-scan the logical map before any such segment can become apparently dead; every temporary sidecar change must be restored before return. A rootless production-C authority regression plus the extracted Device Mapper DISCARD-body regression must corrupt only a later page's mapped-count sidecar and prove the whole range is refused with every earlier mapping, generation and physical reference unchanged. A distinct authority regression must publish two compressed logical mappings in one shared two-block extent through the production stage/finish path with GC accounting enabled, then make only the aggregate live-byte score one byte short after the first modeled removal; the second page's `-EUCLEAN` must restore complete mappings, generations, extent classes, physical references, segment list heads/tails, GC scores, allocation cursors/counters, reserve and role state exactly with zero lower mutations. The same shared-extent regression must then make the otherwise exact aggregate live-byte score one byte high, require `-EUCLEAN` when modeled DISCARD would empty the segment, and prove zero logical invalidations plus complete restoration of the same authority and GC state. A separate final-shared-release range regression must fault-inject (1) a surviving RAW map whose physical START lies inside the shared extent and (2) an unrelated authoritative survivor detached from the segment list while both range pages retain locally valid reciprocal links. Prevalidation must return `-EUCLEAN` with the complete integrity snapshot unchanged; the fail-first diagnostic path must demonstrate that without the preflight rejection page zero can commit before page one reaches the later overlap/list refusal. The direct shared-release proof keeps its descriptive `current_logical`, `last_logical` and `visited_pages` traversal locals in `swapz_verify_shared_extent_release()` so kernel builds and source qualification continue to guard against collision with Linux's `current` macro while the range-only complete-list helper remains isolated to prevalidation. The rootless authority-throughput fixture must characterize dense 1,000- and 100,000-page ranges plus sparse repeated final-map transitions, reporting DISCARD pages, dead-segment transitions, complete-table proof scans, logical mappings examined, thread CPU time, operation allocations, lower READ bytes and decompression calls. A test-only rearm after `swapz_discard_page()` must restore the complete valid map record while preserving the generation incremented by DISCARD; changing only the `valid` bit creates an invalid synthetic extent. If prevalidation fails, report its actual signed result, iteration, map geometry and relevant liveness/mapped sidecars. Timing remains host-specific supporting evidence; it must never weaken or bypass the authoritative full-map proof. The Device Mapper source-contract regression for corrupted DISCARD mappings must compile the actual `swapz_discard` body together with its actual mapper-local extent-bounds helper, so physical-end and segment-crossing failures are executable production-body evidence rather than string-only checks. The preparation codec-result regression executes the production `preparation-slots.h` classifier/publication helper and distinguishes negative errno to ERROR, zero to READY_RAW, and positive length to READY_COMPRESSED; zero/positive outcomes must also be exercised through actual state publication. It must exercise both deterministic publication interleavings, including ERROR winning before RAW selection and RAW_SELECTED winning before a late negative result; the latter proves the target caller still owns fail-closed handling rather than mutating the selected state. It must additionally race one producer and one RAW selector for thousands of iterations and require any observed READY/ERROR state to expose the producer's payload/error side data through the acquire publication edge. The exact engine tests must inject both a successful short lower WRITE and a lower WRITE that physically completes a nonzero prefix before returning `-EIO`; neither may publish a new mapping, trigger verify-after-write readback, or discard a previous authoritative generation. The source-extracted per-extent fallback test must also pair a definitive lower `-EOPNOTSUPP` with an impossible completed-block count and require the original errno, zero credited blocks, no mapping publication, and an abandoned reservation. A separate callback fault must invalidate the active authority token after returning a definitive lower `-EOPNOTSUPP`; the secondary `-ESTALE` from finish must not replace the first lower errno, publish an upper success or release the still-owned reservation. Diagnose the original error, lower-to-finish ordering, completion credit and outstanding ownership, and refuse clean teardown until a valid owner has resolved the reservation. Rootless first-error coverage must also execute the production error-selection helper and source-check every batched replay cleanup plus foreground/GC RAW finalization call site. After successful combined lower I/O, a dedicated exact-engine fault must make the first replay fail `-EBADMSG` and a later paused-tail cleanup fail `-ESTALE`; the caller must still receive `-EBADMSG`, credit zero completed blocks, retain the paused tail, and refuse clean drain until controlled ownership cleanup. A GC engine/RAW failure that retains unresolved authority ownership must elect a terminal target failure even when the first lower errno would otherwise be retryable. The GC exact-engine negative control must repeat the replay/cleanup failure while a rotation owns its destination, repair only the injected corruption without consuming paused ownership, then issue one foreground-like stage and one DISCARD; both must return `-EBUSY` with mappings, allocation cursor, roles and GC ownership unchanged. This bounded serialized interleaving separates terminal errno selection from resource-retention state and is not a kernel race proof. This malformed callback is a rootless error-precedence probe, not evidence that a real block driver reports excess completions. The native fault fixture must verify the acknowledged lower-media prefix against the encoded bytes and the unwritten suffix against zero-filled media; a fabricated partial completion without actual bytes is insufficient. The experimental exact-production-C GitHub workflow must execute the complete native suite with AddressSanitizer plus UndefinedBehaviorSanitizer on both x86_64 and arm64; do not duplicate that expensive pass in the project-goal workflow. On x86_64 it must then clean the native build and rerun the pthread preparation publication/slot-reuse probes with ThreadSanitizer, halting on the first race report. Native ASan/UBSan/TSan coverage is supporting evidence only and must not be reported as KASAN, KCSAN, lockdep or loaded-kernel race qualification. GC engine coverage must also force a fully completed batched lower write whose authority replay fails after at least one earlier extent has published; the wrapper must return the exact committed prefix while leaving the unpublished tail unreachable, so callers never retry already-authoritative pages as though the prefix were zero. A delayed GC lower completion must keep both overwrite staging and DISCARD fenced until replay, and failed GC lower I/O must leave the uncertain physical reservation unavailable for immediate reuse. A combined lower WRITE that reports a short physical prefix and -EIO must publish none of its staged extents, leave previous mappings byte-exact, quarantine all reserved blocks (including unwritten tail blocks), and retry from a fresh range.

The GC native suite must additionally sustain at least 64 all-RAW exhaustion-and-
rotation cycles over a fully populated logical mapper, verifying all surviving
pages byte-for-byte and preserving both rotating reserve roles after every
cycle; a successful mapper construction or two rotations are insufficient.
The sustained RAW oracle must independently track each logical page's expected
mapping generation, incrementing only after a successful foreground publication
or completed GC relocation, and compare every generation alongside byte/CRC
readback after each rotation. The same independent generation ledger is required
for high-occupancy failure-recovery, roll-forward and reserve-exhaustion fixtures
that manually complete survivor relocations: byte/CRC equality alone can hide a
stale authority generation when RAW payload bytes are unchanged. Failed, short
or abandoned lower writes must not advance that ledger. A generation read from
the authoritative map cannot serve as its own expectation. Full-destination roll-forward additionally
requires a subsequent foreground publication, not just a successful role swap;
while a GC lower write awaits replay, the fixture must first prove its
deterministic forbidden-foreground, victim, destination, open-segment and role
identities, then snapshot the recovery token. Commit and destination-advance
attempts must fail without changing that retained token, circular probe,
allocation cursor or any segment role. Failure diagnostics must derive
victim/destination roles from the actual retained IDs and safely represent
invalid/sentinel IDs rather than pairing a changed ID with a hard-coded role
slot. A GC staging-exhaustion diagnostic may report an available reserve or
forward progress only after a side-effect-free authoritative deadness check of
that reserve; a reserve role bit alone is insufficient. It must print the
numeric available-reserve count, original errno, retained authoritative-mapping
state and whether progress remains possible.
When an owned recovery has exhausted the last replacement reserve, repeat
destination-advance and RAW-staging refusals in the existing high-occupancy
rootless oracle. Snapshot and compare the complete authoritative map,
live-record and extent-class arrays across every refusal; also preserve
independent generations, mapped counts, segment roles and program
counts, GC ownership identifiers, allocation cursor/probe, committed blocks
and abandoned blocks. The full, recovery-owned destination is not an available
replacement just because it retains a reserve role. Probe telemetry may rise,
but terminal refusal cannot fabricate forward progress or reuse uncertain media.
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
its mapping and physical liveness reach zero. A separate exact-production-C
engine-rotation regression must model the production survivor-list ordering
`compressed -> RAW -> compressed...`: queue and publish the leading compressed
survivor when the following RAW member forces a GC flush, then inject the RAW
source-read `-EIO` before any destination reservation for that RAW member. The
fault must enter through the same standalone production-shaped RAW relocation
helper used by the successful retry rather than calling the lower-read shim
directly, so the regression proves read-before-stage ordering on the failure
path. The failed read must perform no successful lower read or write, consume no
destination blocks, retain the published prefix without a second generation
increment, and preserve the RAW mapping plus all still-authoritative compressed
source maps. Retry must use the same authenticated victim/destination ownership
and mirror production `swapz_gc_move_raw()` for the RAW member: source read,
RAW authority verification, one-block stage, lower write and `swapz_finish_raw`.
The mixed/batched engine API is not a substitute for this standalone GC RAW
path. The fixture must then read the three remaining 2072-byte compressed
survivors from their authoritative source extents and pack them into exactly one
two-block extent, and prove its physical start refcount is three (with zero
interior refcount). A later foreground overwrite of one member must reduce that
shared reference count to two while preserving the other two maps and their
byte-exact reads. The non-full two-block staging-exhaustion failure diagnostic
must also report source/required-destination extent classes, expected and
observed destination blocks available, the original errno, retained mapping and
recovery ownership, retry disposition, and safe action. This deterministic
source-linked result remains synthetic: loaded lower fault/recovery and
whole-map reuse qualification are separate and must not be inferred from it.
If accumulated uncertain reservations exhaust the owned destination,
qualification forbids cursor rollback, live-reserve reuse or an unbounded
internal retry. When the original
victim has nevertheless reached zero mapping and physical liveness, one bounded
authenticated roll-forward may make the full destination the next victim and
reuse that independently verified-dead original victim as the next reserve
destination. The worker token must remain active and be rebound to that exact
role handoff before foreground mutation can resume. If the old victim is not
fully dead, the operation must remain fail-closed. The exceptional worker
roll-forward path must independently verify every logical mapping and physical
liveness counter, not rely only on segment-mapping counts, before allowing a
recycle hook to touch the prior victim. Every valid map in that scan must have
a legal in-bounds extent class, fit wholly inside one 1MiB segment, and agree
with its extent-class and start-block liveness metadata. A malformed extent
that starts outside the prior victim but overlaps it is terminal; contradictory
metadata must never be hidden by start-block-only segment membership. The exact-production DM GC
error boundary must still reject an integrity/authority failure (-EBADMSG or
-EUCLEAN) as terminal even with a live recovery token, while preserving
retryability for the known synchronous lower-I/O -EIO and per-write -ENOSPC.
The native `gc-recovery-policy.c` fixture must exhaustively check the helper's
eight distinct boolean inputs: recovery inactive/active × READ/WRITE ×
non-`EIO`/`EIO`. The helper receives only the already-classified `is_eio`
bit, so this fixture must not claim independent coverage of individual non-
`EIO` errno values. The separate source-contract regression must prove that
production derives that bit from `lower_error == -EIO`, preserves the original
signed lower errno for terminal reporting, and routes other lower errors through
the terminal failure path. Per-write `-ENOSPC` remains a separate GC capacity
result, not this lower-WRITE retry classification. On helper failure, report the
three policy inputs and expected/observed retry decision.

The GC cost-accounting native regression must force u32 live-byte, u32 I/O-cost
and u16 minimum-block overflow independently after a compressed generation is
durably published. The byte-exact readback oracle must enable the actual
production compressed-extent sequence index before the first publication;
otherwise -EUCLEAN from missing test metadata is a fixture failure, not a
corrupted survivor. Retain the actual read errno in fail-only diagnostics.
Before reporting a RAW replacement as lower-complete, the fixture must copy its
bytes into a bounded contiguous lower-media image and pass those exact modeled
media bytes to authority completion. Survivor validation must read the prior
mapping from that same media image; passing source bytes directly as a completed
write surrogate is insufficient for this adversary. Each lower-complete RAW
replacement must return -EOVERFLOW
without publishing the new generation, changing reserve roles, reusing its
abandoned block or losing the previous byte/CRC-validated payload. After the
bounded failures, a clean replacement must use fresh blocks and publish exactly
one new generation. Emit phase, victim/reserve class, errno, expected/observed
progress and retained-state evidence only on a failed assertion. Saturating
synthetic sidecars cannot establish loaded or full-capacity forward progress.

The native GC retry-policy regression must execute the exact small predicate
included by the production DM target and accept only active authenticated
recovery plus a lower WRITE `-EIO`; no token, a READ, or another error remains
non-retryable. The loaded path then verifies the complete target transition
rather than relying on that predicate test alone.

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
evidence for this state transition. Loaded qualification must additionally use
an owned 5MiB null_blk with exactly three foreground and two reserve segments,
512 logical RAW pages, window one and lower aggregation disabled. It must keep
255 survivors in each of the two closed foreground segments, inject synchronous
lower WRITE attempt 769 after exactly 768 successful foreground writes, observe
one failed GC reservation, resume the authenticated rotation, then observe one
ENOSPC retry after the first reserve becomes exactly full. The following retry
must execute exactly one full-destination roll-forward without a
reserve-degrading destination advance, relocate 510 pages across both recovery
legs, preserve both reserve roles, regain foreground progress, and verify all
512 logical pages byte-for-byte. PASS_LOADED_GC_ROLL_FORWARD_RECOVERY is
mandatory loaded evidence; native-only evidence is insufficient for production
release.

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

### Primary runtime-health diagnostic attribution

The production runtime-health observer keeps the established HEALTHY, WARN,
FAIL and DEGRADED classification contract: definite identity/service/runtime
contradictions are FAIL, incomplete observation is DEGRADED, nonterminal
pressure/error evidence is WARN, and only complete consistent evidence is
HEALTHY. Diagnostic reporting must not promote or demote a snapshot merely to
make it easier to describe.

Every non-HEALTHY reason must have a bounded `SWAPZ_RUNTIME_OBSERVER` record
that identifies the phase and check, expected proof, observed class, originating
command status (or the validated target errno when the terminal status owns the
failure), retained-state disposition, and a safe inspection action. The
`target_terminal` phase is reserved for a validated negative kernel errno;
`failed=1` without such an errno is reported as `target_failure_state` and must
not fabricate terminal-errno provenance. A semantic
mismatch after a successful probe reports command status zero; failed systemd,
dmsetup, inventory or journal probes retain their actual command status. The journal
observer must preserve the bounded `journalctl` exit separately from the redacted
log sample so timeout and probe failure remain attributable without exposing text.
Diagnostics must not print device paths, PARTUUIDs, recovery run IDs or private
journal/recovery text. Every non-HEALTHY `SWAPZ_RUNTIME_HEALTH` summary must
therefore replace its PARTUUID, backing major:minor and mapper UUID/run identity
with an explicit redacted class; the structured observer record identifies the
failed check without echoing those values. WARN and DEGRADED records are observation only: they are
never permission to remove a mapper, disable unrelated swap, delete recovery
evidence, or blindly retry. A sustained GC stall may require the normal primary
stop path, but the observer itself remains read-only and must report inspection
before any operator action.

The exact-SHA systemd/package workflow must execute
`tests/runtime/native/systemd/swapz-primary-runtime-health-diagnostics-test.py`
in addition to the existing shared systemd fixture. The standalone regression
may reuse that fixture's synthetic mocks but must not modify the shared test,
activate real systemd, load a module, mutate swap, require root, or perform
physical-device operations.

The native authority suite must also exercise a fixed 16 GiB maximum-capacity
regression fixture: one protected ordinary-SWAPSPACE2 first page,
1 MiB segment rounding, and the authority's `ceil(logical_pages / 8)` reserve
with its two-segment minimum. It must reject the first page beyond the maximum,
initialize the maximum, attach every capacity-dependent production authority
array, and calculate those array bytes from the compiled C types. The volatile
`struct swapz_map` is currently 20 bytes: raw mappings store their CRC32C in
the four-byte union, compressed mappings store a zero-extended payload offset
in that same union, and compressed mappings additionally retain payload CRC32C
as authoritative RAM state. Encoding-specific readers must not inspect the
other union interpretation. Capacity/RAM oracles must derive this width from
the compiled type and fail closed when source/model accounting diverges. The transaction sequence is retained separately with
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
is the 433,283,072-byte mapping array. As an allocation-free page-table scale
oracle, independently placing each of the 17 rounded arrays behind its own
4KiB-page vmalloc leaf mapping requires 382 leaf PTE pages, or 1,564,672 bytes,
on the 4KiB-page x86_64/arm64 qualification builds. This is deliberately
conservative and is not added to the payload as a measured total: actual
vmalloc metadata, shared upper page-table levels, slab/allocator overhead,
fixed target scratch/caches/workspaces and residency require loaded-host
measurement. The source-contract allocation inventory independently requires
exactly 17 capacity-scaled `kvcalloc` sites (three logical-page indexes, three
physical-block indexes and eleven per-segment indexes), every matching
`kvfree`, exact element types and lengths, and preflight-before-allocation
constructor order. It mutates a copy of the constructor to demonstrate that
an early, differently spelled or resized allocation is rejected. This is a
reproducible production source-size and conservative leaf-PTE scale audit, NOT
an allocator-success or host-RAM PASS. Constructor failure injection on owned RAM-backed `null_blk` and
repeated create/destroy require serialized loaded-host verification; the
native authority suite also performs 17 deterministic small-index failure
injections and a successful attach, repeated eight times with reverse-order
cleanup and AddressSanitizer coverage. That rootless fixture tests owned array
unwind, not a loaded Device Mapper constructor. Never run full-capacity
allocation stress merely to exercise this inventory.
The same preflight must exercise an aligned near-`u32` physical
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
(after excluding the immutable Linux-swap first page and applying 1MiB segment
rounding), keeps the GC reserve at
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
allocator forward progress rather than mapper construction alone.

### Maximum-geometry rootless GC authority proof

The source-derived native scan fixtures in
`tests/runtime/native/gc/scan-scaling.c` and
`tests/runtime/native/mapping/authority-throughput.c` must retain the exact
27,080,192-logical-page admitted geometry (27,080,191 final logical index),
plus smaller scaling rows. Run **actual production authority C** for
zero-sidecar reserve claims, final-map publication and GC role exchanges;
a host-memory scan model is only a comparator. A forged last-entry reference
must be refused even with false-zero victim/reserve sidecars. Recovery role
transitions authenticate physical extent starts and each interior block of
two- and four-block compressed extents, including independent class-only
and liveness-only corruption. Synthetic compressed-map fixtures must clear
the RAW map bit, populate compressed payload metadata, and keep exact
mapped-page sidecars consistent when replacing multiple one-page maps with
one multi-block survivor. Refusals leave roles, cursor and the last
authoritative generation intact. Never replace full-map verification with
cached counts or a reverse-list-only witness.

`tests/runtime/native/gc/high-occupancy.c` must preserve 64 sustained
high-live RAW reserve exchanges and additionally exercise repeated uncertain
writes, byte-exact retries, a physically full GC destination, no-progress
commit refusal, roll-forward to an independently proven-dead victim, and
post-recovery RAW CRC/generation verification. Uncertain synchronous lower-WRITE
completion in this authority fixture must use `-EIO`; `-ENOSPC` is an
allocation/staging result and must be exercised without fabricating a submitted
lower-write completion. Other native compressed/RAW
engine-GC fixtures remain required for actual encoded-byte relocation and
partial lower-run completion; synthetic map metadata alone is not a
compressed byte oracle. A recovery that cannot fit an extent or claim another
reserve must preserve published authority and **fail closed**, not retry the
same uncertain physical blocks or report foreground progress. In the
finite-reserve regression, multiple physically full uncertain destinations
must refuse role exchange; a live last-survivor mapping remains byte-exact,
and exhausted recovery returns `-ENOSPC` without reusing either destination. Deterministic
churn failures must emit a fixed seed, operation index, short bounded
recent-operation trace, failed invariant, expected/actual generation and
the failing invariant's own errno, with generation values read from
authoritative map records rather than mapped-page occupancy sidecars. Successful operations must not log individually or allocate model
nodes.

The kernel-only `cond_resched()` scheduling opportunity occurs at each
4,096-entry logical-map scan interval while the ordered owner retains
authority; that is an *opportunity interval*, **not a 4,096-entry proof
deadline**. At 27,080,192 entries a complete proof still traverses the
full map. Native CPU and monotonic wall observations, including medians
and maxima, characterize only the host fixture, **not loaded-kernel latency
or actual memory pressure**. Any reported maximum verified transition wall
time must include every recovery/metadata proof call that the test places
under that maximum, rather than silently omitting newly added proof paths.
`SWAPZ_GC_MAX_PROOF_WALL_NS`, if explicitly supplied, is an optional
developer-machine-specific diagnostic gate;
shared CI wall results cannot establish any universal acceptable bound.
No native PASS qualifies loaded full-capacity metadata/target peak memory
and allocation success, loaded scheduler and CPU/PSI/tail latency under
concurrent READ/WRITE/DISCARD/FUA, sustained one-hour actual memory-pressure
GC/churn, or authorized physical SD-card byte-exact readback, endurance
and service. These remain independent **NOT RUN** qualification gates.

The native
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

The rootless status wire regression must also exercise the included production
DM_TABLE_STATUS and DM_LIST_DEVICES parsers with fixed-capacity synthetic ioctl
replies and a bounded, deterministic adversarial corpus. Cover UAPI 8-byte wire
alignment, invalid count/offset/length arithmetic, missing name/type/INFO NULs,
forward/overlapping/looping record links, truncated or unterminated UUID metadata,
event-generation drift and INFO failure after an earlier mapping is staged.
Malformed observations must terminate with bounded memory and no partial numeric
CLI output or fabricated all-clear. Impossible counts, including the configured
maximum with an undersized payload, must fail before target-array allocation.
Diagnostic assertion failures identify the record/phase, expected wire bounds,
native-width observed offset/length, parser expectation/observation and original
errno without dumping payload bytes. Preserve valid zero-target and
saturated-padding conservatism. This synthetic evidence is not an atomic
live-kernel snapshot.

Original bounded DM INFO read or snapshot/result allocation errors must retain
their originating errno after the UNAVAILABLE diagnostic, including
EOVERFLOW on exhausted bounded reply growth and ENOMEM on allocation failure.
Print that originating errno in the bounded field-specific diagnostic, not
only in the process errno; never include raw INFO or mapping reply bytes.
Malformed wire records without an originating system error remain BLOCKED with
EPROTO. LIST event-generation drift is transient UNAVAILABLE state and must
retain EAGAIN through both the bounded diagnostic and caller errno rather than
being rewritten to EPROTO. A canonical terminal target status contains both
failed and error: failed=1 with a negative error is FAILED and the diagnostic
must report that kernel errno; failed=1/error=0 is a torn observation that must
retry, while a missing or malformed error token is BLOCKED. The rootless native
observer regression must exercise both INFO read phases using production
parser-backed synthetic snapshots, check safe mapping/device/generation/field
context, and prevent staged numeric output. Error-precedence evidence must also
drive the production dm_query/read_dm_status_observation path through test-only
ioctl interposition for bounded buffer-full exhaustion, malformed reply headers,
and a synthetic syscall errno; fabricating status_problem.failure_errno in a
reader callback is not sufficient end-to-end coverage.

The status implementation must require two consecutive identical relevant
snapshots before printing a ratio. The compressed-only result is available only
when committed counters can partition compressed SWZ extent bytes exactly; an
ambiguous padding configuration reports unavailable. These rootless checks
validate userspace parsing/accounting and build compatibility, not live Device
Mapper semantics; the official acceptance command remains `make test`.

## Retained-window scheduler qualification

For queued-I/O forward-progress review, distinguish a bounded **staged**
64-record window from the potentially longer already-accepted BIO FIFO and
from the separately bounded preparation-slot mask. A 65th accepted BIO is not
a 65th staged array entry. Closed admission, an unready oldest descriptor,
a lower submission error, a terminally cancelled RAW-selected producer and
drain with detached lower I/O must be checked against actual owner/wake
transitions: one ordered owner (or the existing leased submitter dispatch),
the producer that owns its prepared page, and the lower completion callback.
Do not construct a second simultaneous ordered owner to manufacture a
counterexample. Check that success and failure release every remaining
ownership/READY charge exactly once; a worker's early return is safe only
when a real producer, submitter or lower callback can wake it, or the closed
drain explicitly joins and restarts it. Bounded failure-only diagnostics for
such tests identify phase, expected and observed outstanding BIOs, first/last
sequence or slot index, oldest owner, errno or exit code, and latched terminal
failure without BIO addresses or contents. Pure window-policy and lane-gap
tests alone cannot establish those kernel lifecycle facts.

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
evidence must be reported separately and never inferred from this CI. The loaded
owned-`null_blk` phase records the exact running-kernel KASAN, KCSAN and
`CONFIG_PROVE_LOCKING` state when kernel configuration is readable. If any
facility is enabled it snapshots the privileged kernel log before loaded work
and compares only a prefix-stable appended suffix afterwards. Ring-buffer loss,
unreadable diagnostics, ambiguous configuration, or unrelated new debug reports
produce explicit incomplete evidence rather than PASS. Any new KASAN/KCSAN/
lockdep report whose bounded context names swapz is a hard loaded-test failure.
Production kernels with all three facilities disabled remain `NOT_ENABLED`,
not falsely qualified as debug-kernel clean. The ordinary owner loaded stage
may also retain `UNAVAILABLE` when the running-kernel configuration cannot be
read, but a missing, duplicated, malformed, ambiguous or explicit failing
kernel-debug record is not a loaded-stage PASS.

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

The private bounded `tests/tools/quiet-lower-io.sh` sampler must never publish
quiescence based solely on command success or missing fields. Each paired
observation requires the complete current single-line `swapz` INFO schema,
including health/attribution and current-work fields plus its terminal field,
unchanged target geometry and mapping UUID/device/event identity, and two
matching canonical 17-field backing block-stat records. Validate all numeric
tokens and signed Bash arithmetic bounds before comparison; reject malformed,
duplicate, noncanonical or overflowing fields and reject regressions/wraps in
the tracked cumulative attribution counters within a pair and across retries.
Equal samples are not quiescent while block-stat `in_flight` or target
preparation/completion ownership remains nonzero. Shorter 11/15-field block-stat
layouts omit optional discard/flush evidence and are UNAVAILABLE, not zero lower
I/O. Bound every `dmsetup` identity/status observation with a finite timeout.
A failed or timed-out command/read, incomplete status, missing prerequisite,
interval timeout or exhausted finite attempts must report one concise
phase/reason/attempt-count UNAVAILABLE diagnostic, include the command return
code when available, identify retained identity/status/lower samples, and keep
those diagnostic samples separate from withheld published counters. Stable
synthetic fixtures verify only the rootless observer contract, never loaded,
anonymous-swap or physical I/O attribution.

Malformed or incomplete DM INFO status must also report a sanitized parser
detail such as expected/observed field count, invalid token index, a rejected
field key bounded to 64 ASCII characters, or terminal-field mismatch. For a
longer key, report only its bounded length. Never include the raw status line
or untrusted counter values. The owned-null_blk wrapper must propagate this
sub-check detail into its stage diagnostic so status-schema rejection can be
distinguished from active I/O or worker activity without blindly rerunning.
When stable status and lower counters still show outstanding target work, name
the active status field in the diagnostic without printing its value; this
distinguishes a preparation-slot drain from completion-work drain.
Terminal-error coverage must also prove that unconsumed READY preparation
results retire their `prep_ready_current` charge exactly once, while a producer
that publishes after the BIO is failed observes a cancelled state and cannot
leave an orphaned ready result.
The source-derived INFO fixture must include both printf-backed fields and
literal numeric `key=value` fields; deriving the schema from format
placeholders alone can omit a real compatibility token and make only loaded
status parsing fail.

Loaded tests use only newly created, positively owned, RAM-backed `null_blk`. Before and after use, verify device identity, size, major/minor, DM UUID, holders, mounts and active-swap aliases. Never substitute a physical or existing block device.

Before the ordinary loaded smoke target is admitted, qualification must reload
the exact module for each constructor failure stage and force deterministic
`-ENOMEM` after: backing ownership, dm-io client creation, authority/sidecar
initialization, core scratch allocation, per-read-slot scratch, the ordered
workqueue, preparation scratch, and the preparation workqueue. After each failed
create, qualification must read back both the configured stage and a read-only
atomic injection-hit counter and require exactly one hit; an unrelated table-load
failure is not constructor-failure evidence. Every failed `dmsetup create` must
leave the mapper absent, the owned lower with zero holders, the lower block-stat
line byte-identical, and `rmmod dm_swapz` successful. The exact marker
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

Retained-window suspend/resume must drain accepted ownership and verify all pages. Synthetic pre-submission WRITE, READ and FLUSH injection must fail closed. A fresh no-verify mapping must seed one committed nonzero page at a high logical page (2048 through 4095), leaving LBA0 unmapped so asynchronous block-device probes cannot consume the one-shot READ fault. An aligned O_DIRECT pread(2) of that seeded page must return exactly -1/EIO while both target submitted-read requests and owned-lower READ sectors remain unchanged. A helper exit code or byte-verification mismatch alone is insufficient READ-failure evidence. The READ fault seam must cover the synchronous lower adapter plus parallel and asynchronous read-slot adapters and must be rejected on physical backing. Its exact PASS marker, including the verified logical page and `syscall_errno:EIO`, is mandatory loaded-correctness evidence. Upper WRITE errors must be verified at both the target's BIO completion call and Device Mapper's clone end_io boundary, and by a dedicated aligned O_DIRECT pwrite(2) syscall oracle that requires -1/EIO for the injected first WRITE. The end_io hook must preserve prior error statuses and reject new successes after terminal target failure; its counts cannot substitute for the userspace failure gate. These synthetic failures are not evidence for torn/device-originated errors. Recreated owned DM mappings must validate the opened /dev/mapper block node's actual major:minor against the current phase's sysfs DM name and UUID after udev settles, not just dmsetup's name-based UUID. If the deliberately injected WRITE syscall does not return -1/EIO, report the probe return/errno plus write-fault call, injection, failed-state, upper-BIO completion and zero-elision counters before blocking; do not turn this into a pass.

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
An unclaimed `nullb-swapz-<token>` configfs directory is not independently
owned merely because its name has the expected form: preflight must refuse it,
not power it down or report successful cleanup. A proven stale mapper's lower
config may be removed only after exact run-token, index, memory-backed, mount,
swap, and mapper/device identity proofs, and any failed power-off or configfs
removal remains a BLOCKED disposition. An index collision with a different
run's null_blk must not be adopted.

Before completion-only scratch cleanup or device mutation, loaded preflight
must distinguish absent host CAP_SYS_ADMIN (NOT_AUTHORIZED) from a reproduced
source/test FAIL, audit its commands, and inspect null_blk module discoverability
without loading it. A retained package journal belongs to package recovery;
it must not be erased to make the benchmark advance. An available but
contradictory running-kernel debug .config is BLOCKED with its named check;
an entirely unavailable .config remains UNAVAILABLE, not a fabricated debug
PASS. The initial MemAvailable sample is observation only, with the 1 GiB
admission floor owned by later ID36. Preflight safety refusals use bounded
`BLOCKED: LOADED_PREFLIGHT=<NOT_AUTHORIZED|BLOCKED> check=<fixed-name>
errno=<numeric|unavailable> remedy=<bounded-action>` diagnostics. Numeric
`errno` is reserved for a captured operating-system error; semantic
mismatches and external-command failures use `unavailable`, with a bounded
command status in the remedy when useful. Mount and swap inventory are
tri-state safety proofs: `findmnt` status 1 alone means no matching mount,
status 0 must include a mount identity, and any other status is BLOCKED;
`/proc/swaps` must have the canonical header/record shape and distinguish an
owned match, proven absence, and read/parse failure. For an owned block source,
preflight must compare every block-device swap entry by device identity so a
`/dev/dm-*` alias cannot hide an active `/dev/mapper/*` mapping. A block-swap
entry whose path cannot be resolved to a readable block device is BLOCKED
because its identity cannot be proven different; unrelated swapfiles remain
untouched. A stale mapper UUID must match an exact currently emitted owned
phase for the same run token; arbitrary suffixes are never ownership proof. Resolved null_blk `dev` telemetry must be one canonical
newline-terminated major:minor record, not a prefix of malformed or
multi-record input. Unexpected Bash failure remains FAIL with its numeric
status and source line. Rootless tests must run a private transformed
fake-proc/fake-sysfs preflight with stubbed privileged commands for each refusal
and prove unrelated swap remains untouched. No test may select arbitrary
`/dev` fallback for a configured PARTUUID or remove non-owned /tmp occupants.

The private loaded preflight is an executable repository helper and rootless
qualification must fail if its executable bit is lost. Privileged orchestration
still invokes shell helpers through `bash` inside the watchdog, but repository
mode is part of the harness contract and must not silently drift. Preflight's
required-command audit must include every unconditional utility it executes.
Mapper enumeration and lower-dependency parsing are explicit fail-closed
operations; they must not rely on an unguarded pipeline/assignment under
`set -e`. Busy-module `dmsetup ls --target swapz --noheadings` records
must contain one bounded mapper name and one parenthesized canonical
unsigned-decimal device number, without leading zeroes. Support both
`(major:minor)` and `(major, minor)` forms emitted by dmsetup versions;
the parser normalizes either exactly to `major:minor` for the subsequent
independent mapper-node identity comparisons. The comma-space form occupies
three whitespace-separated fields; neither form authorizes removal by itself.
Empty lines, extra fields, noncanonical numbers or `No devices found` are
not proof of a single owned mapper: refuse at `mapper_inventory` before any
holder signaling or device cleanup, report pipeline status and safe inventory inspection,
never echo inventory/device paths. On any failed enumeration, capture both pipeline statuses before running
another shell command and emit a bounded failure-only category identifying
whether `dmsetup` itself failed or the strict AWK record parser refused its
output. The reporter may attach `mapper_inventory_failure` with only
`source` and numeric `exit_code` on a loaded preflight failure. This is
read-only diagnosis and does not promote or bypass the existing mapper
inventory BLOCKED gate; neither raw mapper names nor device paths are printed.
The parser may retain at most two validated
records because any second mapping already proves cleanup ambiguity. For the
single admitted record, its decimal major:minor is part of the ownership proof
and must match both the mapper node and its canonical resolved node before any
holder signal or mapper removal; a syntactically valid but stale/raced device
identity is `mapper_device_identity` BLOCKED, not ownership proof. Stale-mapper identity, UUID, open-count and lower-device validation
must avoid runtime-dependent Bash extended-regex capture state; exact shell
patterns and guarded parsers are preferred so malformed input reaches an
explicit `BLOCKED:` path rather than shell status 2. Canonical mapper identity
checks must separately guard both `stat` calls before comparing device IDs. All native interface/source-contract tests that describe this ownership proof must assert the same exact shell-pattern/token contract and must not retain obsolete `BASH_REMATCH`/extended-regex expectations. The privileged preflight safety path must avoid runtime `=~` expressions and C-style arithmetic commands entirely; numeric sysfs/dmsetup fields are accepted only as canonical unsigned decimal text (`0` or a nonzero value without a leading zero), and bounded retry loops use fixed shell iteration lists. Running-kernel release validation follows the same rule: a successful `uname -r` result must be 1–128 ASCII characters, begin with an alphanumeric character, contain only `-0-9A-Za-z._+~`, and be checked with locale-fixed shell patterns before it is interpolated into `/boot` or `/lib/modules` paths. This keeps malformed host state on explicit fail-closed `BLOCKED:` paths instead of Bash runtime-status paths. Native source/interface contracts and rootless literal checks must track those exact non-arithmetic preflight forms (`[[ $refcount == 0 ]]` and `[[ ${#swapz_maps[@]} == 1 ]]`); obsolete arithmetic spellings are not valid compatibility requirements. Because ordinary preflight safety rejections emit `BLOCKED:` and exit one, a
status-two preflight return is classified as a shell/runtime harness failure and
must emit a concise `FAIL:` marker rather than disappearing behind filtered
stage-5 output. Rootless verification must run `bash -n` across every harness shell script individually to ensure syntax regressions fail rootless Stage 2 rather than reaching loaded execution. The rootless harness must also prove that
`source-contract-test.py` contains exactly one terminal test runner; duplicated
tails or duplicate `__main__` blocks are harness corruption and fail before
loaded qualification. Shared benchmark-plan construction must emit fixed allocation/fixture/trace/write-plans/verify progress markers before each fallible setup class. If that setup returns nonzero without a separately allowlisted diagnostic, the reporter must publish only the fixed step name and a bounded fixed reason; it must never copy the failing command, path, fixture bytes, or arbitrary stderr.

Unexpected preflight command failures must be trapped
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
remain excluded from published diagnostics. An explicit
`FAIL_PRIMARY_NULLBLK_LIFECYCLE:` marker takes precedence over a
missing overall lifecycle PASS record: classify it as FAIL and use the named
phase plus only the sanitized coordinator detail. A validated
`PRIMARY_PREPARE=FAILED phase=... errno=... error=...` record is itself
sufficient for the sanitized prepare sub-check, even when the helper
intentionally omits its captured command-wrapper line; parser regressions must
cover both output shapes. If an explicit lifecycle FAIL marker is paired with
child exit 0, the report must still classify the stage as FAIL, preserve
`child_exit_code: 0`, and append
`expected=nonzero observed_exit=0 evidence=recognized-failure-marker` to the
sanitized diagnostic. Its regression must cover both the matching nonzero
child exit and the contradictory zero exit. The private owned-null_blk qualification report must bind the same live host
digest as production: `swapz-host-v2` with its terminating NUL, canonical
lowercase 36-byte DMI product UUID in `8-4-4-4-12` hexadecimal form, and
lowercase 32-byte machine ID. Its two
host-identity records must use the same trusted byte-input rules as production:
root-owned single-link non-group/world-writable regular files, no symlink
following, stable metadata, bounded reads, and exactly zero or one trailing LF.
A stale machine-ID-only digest, CRLF-normalized record, or otherwise untrusted
input must not be silently accepted; native regression must keep the private
report fixture aligned with production host identity. The x86_64 private
rehearsal's DMI fixture must accept the canonical five-group 8-4-4-4-12 UUID
and reject a spurious sixth four-hex group; an overly long regex would refuse
valid hosts and could incorrectly accept malformed records. Only the digest may appear
in evidence, never either raw host identifier. On Linux aarch64, the private
owned-null_blk test build alone may use a trusted root-owned single-link
`/etc/machine-id` under the same strict grammar, hashed as
`b"swapz-nullblk-arm64-v1\0"` plus 32 lowercase bytes. Its report declares
`aarch64`, and only the private owned-RAM parser and running-kernel check
accept this machine-scoped digest. It is not a hardware identity: the
installed/physical parser, DMI-bound production host digest, bare-metal
x86_64 physical admission, and official history eligibility remain unchanged.
The official ARM64 report with missing DMI stays `host_identity=UNAVAILABLE`
and may not be treated as physical qualification. The private ARM64 build
must exclude its otherwise unused DMI UUID normalization helper so the
`-Wall -Wextra -Werror` lifecycle binary compiles without weakening warnings;
installed and x86_64 builds retain the existing normalization and checks.
Each owned-null_blk lifecycle
rehearsal must allocate
a fresh root-owned evidence directory bound to the same
random ownership token used for its null_blk config. Clean teardown may remove
only that exact token-bound directory after the holder/mount/swap identity
checks pass. Quarantined evidence from an earlier run is retained for
investigation but must not block a later independent rehearsal merely because a
fixed historical evidence path still exists. Loaded correctness qualification
must require the canonical primary lifecycle PASS record, the exact ordered
thirteen initial start/stop fresh-process interruption PASS phases plus the five
fresh-process recovery interruption phases, the resulting eighteen-case
interruption-recovery aggregate, and the separate thirteen-case negative-recovery
aggregate. Missing, duplicated (including repeated lifecycle or aggregate PASS
records), substituted or malformed lifecycle markers make Stage 5 evidence
incomplete; the parser must not silently overwrite an earlier PASS match.
Merely executing the helper or recognizing its failure markers is not sufficient
for a qualification PASS. The loaded report parser must require those same
eighteen phases in canonical order and the `cases:18` interruption-recovery
aggregate; any smaller aggregate is incomplete evidence. Every direct primary
lifecycle command in the owned-null_blk rehearsal, including metadata-only
`prepare` and diagnostic `plan`, must have a finite process watchdog; ordinary
test operations use the same 90-second TERM-then-KILL ceiling, while final
cleanup recovery retains its separate 60-second ceiling. With the eighteen-case
matrix the complete success path can issue at most 144 such 90-second commands,
so the loaded-stage aggregate watchdog must remain at least 14,400 seconds,
above the 12,960-second command ceiling with bounded setup/cleanup headroom.
Increasing coverage may raise the aggregate watchdog but must never lengthen or
remove an individual lifecycle timeout. Synthetic Make-interface and report
fixtures that model a successful loaded stage must emit the same current ordered
lifecycle phase set and aggregate case count as the real loaded parser; stale
fixture markers must fail rather than silently weakening evidence validation.
Source-extracted lifecycle C fixtures must select the concrete function
definition rather than an earlier forward declaration, and must not include a
production helper body when the fixture already supplies a stub for that
helper. Each extracted or stubbed function must appear exactly once in the
generated translation unit, which must compile with the production fixture's
strict warning flags.
The normal-stop matrix
must include fresh-process death after durable STOPPING, after native swapoff,
after exact mapper removal, after owned-module unload, and after durable
RESTORED before terminal COMPLETE/owner release. Recovery from those later
stop checkpoints must not recreate already-removed kernel state and must retain
the durable interrupted-stage provenance. The start matrix must include the
post-header/pre-module INTENT shape, the
post-`finit_module`/pre-LOADED INTENT shape, the verified inactive-table
mapper shape before resume, and the post-mkswap/pre-swapon shape. This exercises
recovery with module-absent/module-present INTENT state, exact inactive-table
clear/remove, and a fully formatted but not yet activated mapper. The separate
negative-recovery aggregate must require all thirteen mandatory cases, including
definite pre-effect `EIO` failures for both `swapon` and `swapoff`, and
must carry `definite_io_error:true`. Those definite errors are never reconciled
as ambiguous success: start remains recoverable without activation, and stop
preserves the active mapper until a later independently successful normal
`swapoff` proves deactivation.
The private qualifier may print the coordinator's expected
`BLOCKED: primary-swap <operation> failed: <bounded strerror>` while
deliberately injecting those failures. The official reporter may exclude
at most one operation-correct refusal per enumerated negative case from its
global `BLOCKED:` gate only when all thirteen start markers are present in
canonical order, the negative-recovery aggregate and terminal
`PASS_LOADED_TEST_EXECUTION` marker are present, the independently parsed
loaded-correctness oracle passes, and the child exits zero. Missing, malformed,
duplicated, out-of-order or out-of-scope refusal markers, unexpected operations,
private text, any explicit `FAIL:`, an unrelated privilege/quarantine refusal,
or a nonzero child exit must still fail/block qualification.
Progress for an operation-correct negative-case refusal is observational, not
an overall BLOCKED or independently sufficient PASS. The ID61 source-contract
test verifies the progress helper's scoped negative-case context and the
authenticated-refusal filter, not the obsolete one-argument spelling.
The qualifier itself must authenticate each refusal-producing negative case
before emitting its child output: child exit must be exactly 2, the optional
selected-fault marker must be exact, the single `PRIMARY_START/STOP/RECOVER=FAILED`
record must carry the case's fixed errno and C-locale strerror with bounded
phase/persistence/resource fields, and the following `BLOCKED: primary-swap
<operation> failed: <strerror>` wrapper must match exactly. A timeout,
unrelated nonzero exit, missing/duplicate line, wrong errno/cause, malformed
resource field or extra sideband is a harness FAIL and must not be echoed.
The privileged manager must suppress both output streams from its pinned
`mkswap` child so tool status text, including generated identifiers, cannot
enter the coordinator's authenticated refusal output. The child still reports
failure through its exit status and the manager's bounded structured record.
The source regression must require a verified `/dev/null` output descriptor
and redirection of both child streams before `fexecve()`.
For the reporter exemption, the fixed case-to-refusal contracts are:
`swapon-eintr-noeffect=start/EINTR`,
`swapon-eio-noeffect=start/EIO`,
`post-swapon-inventory-eio=start/EIO`,
`swapoff-eintr-noeffect=stop/EINTR`,
`swapoff-eio-noeffect=stop/EIO`,
`swapoff-ebusy-noeffect=stop/EBUSY`,
`post-swapoff-inventory-eio=stop/EIO`,
`state-dir-fsync=start/EIO`, stale-run and lost-provenance as
`recovery/EPERM`, and wrong-mapper-identity as `recovery/EEXIST`. Stale-run
and lost-provenance are admission refusals and must preserve the exact durable
state bytes. Wrong-mapper is different: recovery may first normalize the
interrupted STARTING record to durable
`RECOVERY_REQUIRED(previous=STARTING)`; that exact transition is required,
while the foreign inactive mapper, ownership records and host swap identity
must remain unchanged. The two applied-EINTR reconciliation cases emit no
refusal. The reporter must authenticate all thirteen ordered case-start records and all
eleven required refusals whenever the overall loaded-correctness parser reaches
PASS; authentication is mandatory even if **zero** detailed case records are
present. One missing, duplicated, wrong-cause or wrong-operation refusal, or an
aggregate-only `cases:13` claim without the detailed sequence, invalidates the
entire exemption and fails the loaded evidence contract. Canonical synthetic
PASS fixtures used by report and Make-interface tests must model that same
13-case/11-refusal sequence and the terminal `PASS_LOADED_TEST_EXECUTION`
marker; aggregate-only synthetic fixtures are intentionally invalid.
If any case-start or negative-recovery completion marker is present while
loaded correctness is incomplete, authenticate the attempted matrix as well:
an incomplete or malformed attempt is a harness FAIL. A complete matrix may
authenticate only its own expected refusal lines; it does not override another
incomplete loaded gate, which still prevents stage PASS.
That authentication failure is a harness FAIL. Independent explicit
`FAIL:` evidence keeps its own failure phase, while unrelated
`BLOCKED_LOADED_QUALIFICATION:` evidence remains BLOCKED; neither is
reclassified merely because the negative-refusal matrix itself authenticated.
The human qualification summary
must also display the verified process-death recovery count and negative-case
count so reviewers do not need to infer lifecycle coverage from raw log text.
Failure attribution must be scoped to the current negative-case start marker;
an earlier authenticated refusal must not replace a later lifecycle failure's
phase or diagnostic. The report regression must cover consecutive negative
cases with different expected operations. Lifecycle refusal checks must keep
the human operation label separate from its structured record name: recovery
uses the wrapper label `recovery` and the protocol prefix `PRIMARY_RECOVER`.

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
the clean source fixture case. Direct compile-only Kbuild invocations without
an explicitly supplied generated header must stage the checked-in unknown/0
fallback even when a stale root build header exists, and therefore cannot
qualify a clean module. Staging must also prune source C/header files that no
longer exist while preserving Kbuild-generated files; otherwise a removed
header can silently satisfy a later compile from stale staging. Any changed
staged input invalidates the previous candidate before replacement. An
explicitly missing generated header, missing or invalid VERSION, or failed
Kbuild must leave no previous candidate image. Rootless W=1/W=2 and normal
staging regressions must preserve unchanged source identity, independently
observe tracked kernel-input and release changes, refuse dirty/unknown
provenance, surface genuine missing-header diagnostics, and retain the original
failed build phase and exit.

### Dedicated SD performance and sustained-workload qualification

Physical performance qualification is separate from the mandatory owned-RAM
matrix and does not change the single supported \`make test\` interface. It is
scheduled only when the current protected target passes the physical identity,
source/artifact and lifecycle gates in \`AGENT_CONTEXT.md\`; no agent may start it
while another host task owns the card. The private implementation is
\`tests/runtime/benchmark/{sustained-replay.py,anonymous-swap.py,qualification.py,physical-campaign-evidence.py}\`.
The campaign-evidence helper is read-only with respect to devices and does not
schedule workloads; it snapshots and seals scheduler-produced evidence.
The sustained raw-device replay must independently validate the immutable
Linux v1 SWAPSPACE2 header (including byte-swapped v1 version, declared last
page and exact device-byte geometry) before opening a raw WRITE path. The
kernel can map valid sparse bad-page layouts, but the current raw benchmark
uses one contiguous PAGE-offset span. Until that benchmark implements an
equivalent clean-segment translation, it must fail closed for a shorter
declared area or any bad-page entries, never write through those gaps, and
never treat the trailing SWAPSPACE2 signature alone as admission.
Rootless adversarial fixtures must prove these refusals and header preservation.
The physical-campaign evidence test and sustained-replay entrypoints remain
Git-tracked executable files (mode 100755); the rootless source-contract suite
must detect accidental executable-bit loss before running physical benchmarks.
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
4096 so it cannot overwrite the immutable `SWAPSPACE2` first page. Swapz
replay requires exactly the
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

The synthetic anonymous-page generator must reject invalid page counts before
allocating its schedule, accept only unsigned 64-bit integer seeds, and keep
fixture page indices within 0..65535. Valid seed/index/profile recipes remain
byte-identical. It must refuse liblz4 measurements of non-4096-byte pages and
reread each written page against the deterministic recipe and whole-fixture
SHA-256 before writing its sidecar. The reread must reconstruct the complete
manifest, including measured liblz4 buckets and byte accounting, and compare
JSON value types exactly; Python bool/int or float/int equality must never make
mistyped metadata acceptable. Truncated, extra or changed records and any
workload-metadata mismatch are failures, not qualification.

The permanent rootless regression for this contract is
`tests/runtime/benchmark/anon-page-fixture-test.py`, registered in
`tests/Makefile` and invoked by the existing official rootless test stage.
It must import the actual fixture generator/verifier, not a copied or
mock-compressed implementation. Only real liblz4 (when available) may
measure compression; missing liblz4 skips those measurements while the
seed, page-index, schedule-limit, recipe and size guards remain exercised.
Keep test payloads bounded to 18 regular-file pages (73,728 bytes) and
persisted manifest reads bounded to 16 KiB. Verify the complete persisted
manifest with exact JSON types, including boolean- and float-as-integer
rejection, every missing or unexpected top-level field, RAW counts and
bytes, compression descriptor, weighted profile quotas, nested measured
histogram counter types, and the fixture SHA-256. Check oversized seed
text, invalid seeds/counts/indices, short and trailing records, and
tampered first/last page bytes. Metadata-test failures must name the field
and bounded expected/observed metadata summaries; record failures must
name the page plus expected/observed sizes or SHA-256 digests. Never dump
raw page contents in diagnostics. Freeze SHA-256 page digests for all nine
existing recipes and complete 16-page default-weight fixtures for seeds
0, 0x51A0A9 and UINT64_MAX to guard byte-identical existing workloads.
A failed manifest write must not emit success. The same suite must execute
the real anonymous-swap worker's `run` function with bounded synthetic
dependencies and a 64-page in-memory mapping, inject `BufferError` from
`mapping.close()` after an otherwise successful round, and prove the PASS
result writer was not called while cleanup records
`mapping-close-failed` and `BufferError`. Rootless synthetic PASS remains
distinct from actual kernel anonymous swap-out/swap-in, loaded-host and
physical-device qualification.
The anonymous-swap worker independently compares every 4096-byte page on
every admitted reread; failed comparisons report the phase, page index and
expected/observed digests and cleanup outcome. PASS is written only after
the anonymous mapping closes successfully; rootless fixture checks do not
establish physical swap-in evidence.

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
brackets. Peak target RAM is sampled on a 100 ms cadence from a one-second
pre-create baseline through mapper initialization, steady operation, measured GC and
ordinary mapper teardown, followed by at least two seconds with the mapper
observed absent. Consecutive monotonic samples must remain within 50–150 ms;
larger scheduling gaps are incomplete evidence because they can hide the RAM
peak. Each sample records \`MemAvailable\`, \`SUnreclaim\`,
\`VmallocUsed\`, UTC time, a monotonic timestamp and mapper-presence state.
The trace preserves the three \`/proc/meminfo\` integers in their
kernel-reported \`kB\` units and declares \`meminfo_unit: "kB"\`; the
shared validator's strict parser rejects missing, duplicate or wrong-unit
fields, and the validator alone converts them to bytes before applying the
ceiling. A trace
that relabels byte values or silently treats KiB integers as bytes is invalid.
Mapper-present means the exact source-bound mapper UUID named by the trace, not
merely some Device Mapper node. The qualifying
peak is derived from the raw samples as baseline-median
\`MemAvailable\` minus the minimum \`MemAvailable\` from the first
initialization sample through the last mapper-present teardown sample. This
charges constructor allocations that occur before Device Mapper publishes the
exact mapper UUID while excluding unrelated post-removal recovery dips; an
asserted replay scalar is diagnostic only. The final target-absent
second must return the median \`MemAvailable\` to the baseline envelope
without leaving \`SUnreclaim\` or \`VmallocUsed\` above their pre-create
envelope. Repeat the same whole-host sampler for the raw control when collecting
the physical comparison. This observation is deliberately conservative rather
than exact target attribution, but an estimate from C type sizes alone cannot
satisfy the gate. Reports include useful throughput, p95/p99,
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
emits campaign_status PASS for a complete v2 PASS with stable source/tree,
full kernel identity, CPU model/policy/affinity, total RAM, mount and swap
inventories, device identity/queue/scheduler and module cleanup state. The sealed
campaign also publishes the normalized admitted target tuple (lowercase PARTUUID
and exact partition byte size) derived from the stable before/after snapshots;
release aggregation must bind to that tuple instead of trusting a separately
typed device label. A v1 numerical PASS is sealed as BLOCKED rather than
promoted. Host lower-WRITE reduction is not a direct NAND endurance/wear
measurement and must not be reported as one.

The independent physical evidence audit must classify missing, stale, screened,
excluded, malformed or otherwise unusable evidence as BLOCKED, not infer a
measured failure from an incomplete evaluator decision or from false checks
attached to an unauthenticated cohort. A FAIL requires either a producer's
terminal failure authenticated against the exact source, host boot, physical
arm chronology and prospective pair identity, or a complete accepted cohort
with a coherent measured failure decision. A failing preflight, missing producer error or unknown measurement provenance
remains BLOCKED even when an original arm says FAIL.
A missing or unrecognized producer phase must remain BLOCKED; the audit must
never synthesize a generic failure phase. Check every attempted index, duplicate
pair/run identifier, exact counterbalanced raw/swapz temporal order, source and
admitted-target binding; a duplicate identity or overlapping chronology
invalidates every implicated failure witness, not only the later record.
Retain excluded attempts rather than filling them with replacements. The audit
must retain the
first failing cohort/pair/arm, required versus attempted/accepted pair counts,
evidence class and validated source SHA/target PARTUUID without printing private
host paths or unsanitized producer errors. The original producer stage, error
and source artifacts remain immutable; diagnostic redaction must never erase
them. Rootless synthetic fixtures test these dispositions and must never be
used as authenticated physical measurements. A qualifying already-sealed
artifact with verified digests must be reused rather than triggering a
redundant physical campaign.


## Report contract

Official human-readable and JSON reports use `swapz`, not implementation-generation labels. Schema keys are version-neutral. SWZ names the legacy internal extent codec, not an authorized physical-partition format.

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

### Terminal report integrity

The local report write is part of qualification integrity and completes before
Git publication or history refresh. Serialization, temporary-file write/chmod,
atomic replacement, cleanup failure or interruption must fail closed: never
publish Git evidence or refresh history for that run. A prior test-stage failure
remains authoritative if final report handling also fails. When all test gates
had otherwise passed, a report failure makes the run INCOMPLETE and nonzero;
an interrupt with no earlier failure returns the conventional interrupted
status. Cleanup is secondary and must never replace the originating report-write
exception. Public diagnostics contain only the fixed report-write stage,
integrity classification, bounded observed category and numeric errno when
available; they never emit exception text, traceback paths or the temporary
file name. Any pre-existing report is explicitly not evidence from the failed
publication attempt.

### Evidence-monotonic report publication

Report publication must be strictly evidence-monotonic. When publishing
`test_results.json` to `origin/main`, if `origin/main` has advanced while
the test suite was running, the publisher fetches `origin/main` and inspects
the remote report. Newer-source evidence is protected by
`git merge-base --is-ancestor local_tested remote_tested`: a remote tested
source that is a descendant of the local tested source causes
`SKIPPED_GIT_SYNC`, so delayed runs cannot overwrite newer qualification
evidence. A concurrent main advance that merely inherits the unchanged report
for the same tested source remains eligible for publication. If the fetched
head instead changes `test_results.json` while still reporting that same
tested source, preserve the remote canonical report but archive the delayed
host's result as an intermediate report-only commit, followed by a commit that
restores the original canonical tree. Both commits are sent in **one**
nonforce fast-forward push, so the public canonical file is never replaced by
the delayed result; the intermediate revision remains accessible in Git
history. An algorithm-only run similarly archives instead of replacing a
same-source full-tier canonical report. Identical reports are not duplicated.
The local delayed report remains available without resetting the working
checkout. Restoration commits use the normal report-only subject for exact
source identity, with a `swapz-canonical-restore: true` trailer that the
history plotter ignores to prevent duplicate history points. Report comparison,
restore-tree, and ancestor errors fail closed with `GIT_SYNC_FAILED`.
The local-bare-Git concurrency regression uses text-mode Git subprocess
output, and verifies the archived revision, restored public tree, unaltered
local checkout, and restoration trailer without coercing SHA strings to bytes.

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

The rootless summary labels its source-inspection phase "Source code and safety
checks"; this is display-only and does not change source-phase identifiers,
execution, qualification or failure attribution. Source contracts show
structure, not loaded semantics. Native C shows portable product logic, not
Device Mapper runtime. W=1/W=2 shows compilation, not correctness. Owned RAM-backed loaded tests show real kernel BIO behavior on the test host, not physical-media benefit. Behavior on a particular real device requires physical evidence from that device. The current dedicated SD-card target already has standing owner authorization under AGENT_CONTEXT; no additional per-run reviewer/owner permission upgrades a lower evidence level into physical evidence.

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
The plots use synthetic RAM-backed benchmark evidence, not physical-device
qualification. Preserve historical overall PASS reports under their existing
host-provenance rules; also admit overall INCOMPLETE only when all five
required RAM qualification stages explicitly PASS. Overall FAIL/BLOCKED
or any incomplete RAM stage remains excluded. Persist each original overall
verdict and the five-stage evidence status in history.json and CSV; allowing
an INCOMPLETE report into descriptive RAM plots never upgrades qualification.
Require default async preparation and a recorded delta64 state for mixed
points, and matching source/fixture/trace between each pair. Delta64
off and on are separate series: the production default became rescue-on, so the
line breaks there instead of joining LZ4-only history. Exclude
failed/blocked reports and other or unproven hosts. If no proven overall
PASS report matches the selected computer, history generation stays NOT UPDATED
with an explicit absence-of-evidence notice, not a generic plotting failure.
RAM stage PASS with overall INCOMPLETE never becomes qualified PASS history.
Never pool optional delta64
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
successor/dwell bin transitions. A rejected partition with a non-null output
(zero/missing mark or reversed completion/submit endpoints) must leave **all
six** previous output fields unchanged, not merely the final seal field. A null
output is rejected independently; because no output object exists, no
preservation assertion applies. Initialize distinct nonzero sentinels before
invalid non-null cases and preserve a valid partition across the 64-bit reversal
boundary; a partially overwritten rejected attribution is a regression even if
the boolean return value is correct. Fail-only native diagnostics identify the
phase, relevant timestamp boundaries and whether rejection itself failed; for a
non-null rejected output they additionally identify the first differing field
and its expected/observed value. This passive contract does not count accepted
BIOs or qualify kernel drain progress. Rootless source contracts forbid scheduling,
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
  shared extent/first-data-block payload caches.
- **ID63 adjacent READ coalescing:** production keeps `read_coalesce=1` by
  default. Retain five matched fast rounds and five matched serial-depth rounds.
  For the ordinary packed-read workload, populate logical pages in ascending
  QD32 vectored-write waves before the timed sequential and seeded-random QD32
  reads. This gives the fixed fixture reproducible packed placement while
  retaining multi-page input. Setup is outside the measured READ scope and
  does not relax the required observed-merge evidence. The separate
  allocation-bounded ID36 path retains its QD32 persistent write/read lanes.
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
alternative test entrypoint; `make test` runs algorithm/RAM checks,
`make test_full` retains the integration suite, and `make fast_test`
remains development-only.

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

A missing later stage is `NOT_RUN` for diagnostic presentation, not an
invented `stages[]` PASS record. `UNAVAILABLE` denotes evidence that could not
be obtained or verified (such as an artifact digest); `FAIL` is an observed
failed check and `BLOCKED` is a refused qualification gate. These are
distinct from each other and from `PASS`. A fail-fast record retains only
the stages actually executed; a full PASS requires all five in canonical
order, exact clean tested-source identity, matching kernel/build provenance,
the required loaded verdicts, and final formatter/module/oracle digests.
A report-only advance of `main` may preserve the tested source, but cannot
make a stale source, changed implementation, dirty input, missing stage or
missing artifact current qualification.
A report published late for an older source after a newer code commit remains
historical evidence, never qualification of the newer code. Development physical
admission may traverse it only if its sole changed path is the canonical report,
its subject and embedded source/tested commit match an ancestor, and any
archive-and-restore pair exactly restores the prior tree. This cannot bypass
fresh current-main source-built evidence, device admission or recovery checks. Before recording or publishing PASS,
the runner must also require the actual kernel release, valid current
hardware-bound host identity, exact clean generated build-source header and
byte-exact formatter/module/oracle digests. A failed binding refuses PASS
with a sanitized phase/reason; FAIL/BLOCKED reports remain historical evidence
and cannot be promoted by subsequent report-only commits.

Build provenance and the qualification runner must resolve a report-only
`main` descendant to the same nearest non-report source commit. The Makefile's
generated `SWAPZ_BUILD_SOURCE_SHA` must exclude only the root `test_results.json`
path when selecting the latest code revision; otherwise rebuilding after a
report publication would stamp artifacts with a report commit while the
runner correctly records its source parent. The Make-interface regression
must exercise a synthetic main-only history containing a report-only commit,
prove both identifiers resolve to the source commit, and prove a later source
commit becomes the new identity. It must query the parsed root Makefile at
each committed source identity and after a dirty source edit, preserving
the clean-state distinction, and require the official reporter's `git_sha()`
to resolve the same synthetic repository revision in every phase rather than
validating only a duplicated Git expression. Its separate incremental-build
mock may live under the outer ignored `build/`, but it must initialize its
own non-main Git checkout and track the fixture inputs before qualification.
Initial and unchanged runs must bind the copied Makefile and reporter to that
fixture SHA with clean 1. Later intentional source edits remain uncommitted
development changes: they retain the same source SHA, generate clean 0, run
the synthetic stages for incremental timestamp checks, and must refuse
qualification at report binding rather than claim a clean tested source.

A report-only-looking commit with a noncanonical subject is not a report
commit: `git_sha()` must retain that commit as its source identity while the
Makefile's path-based source resolver skips its report-file change. A focused
synthetic history must preserve this disagreement as an explicit fail-closed
provenance mismatch; do not broaden the report-commit subject matcher to hide
it.

After writing the file, `make test` automatically publishes only that report
to `main` using Git plumbing. `tested_commit_sha` names the nearest
non-report code revision; generated report-only ancestors modify only
`test_results.json` and do not become new code revisions. Source revision
normalization has no fixed report-chain depth, so repeated qualifications of
unchanged code cannot eventually turn a report-only commit into tested source.
The report is built on the actual current main head so report-on-report updates
remain normal fast-forwards. A claimed PASS is rejected before Git plumbing
unless the complete canonical stage matrix and live host/kernel/build/artifact
bindings are valid; an incomplete or contradictory synthetic PASS must never
be published even if its two source fields agree. Transient push/fetch failures receive a bounded
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

Idempotent first-data-block payload-cache invalidation qualification must
preserve the existing explicit-invalidation and post-write miss tests. Source
coverage requires the 512-slot tag invalidation to remain guarded by a nonzero
legacy-named `read_metadata_lru_clock`, with the clock reset by that invalidation
path. Native coverage must call the mutation fence twice before a reread and
still require the expected lower payload-block read, proving repeated
invalidation changes no observable authority behavior.
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

Repository-policy CI audits individual pushed first-parent commits. Each
implementation, test, packaging, workflow or build-interface path requires a
non-whitespace edit to an *applicable* canonical standards file in the same
commit. Product source accepts coding or testing standards; the kernel Kbuild
Makefile and release VERSION additionally accept compile standards. Benchmark
tests accept testing or benchmark standards; other tests require testing
standards. Build/package-focused workflows (`product-codec.yml`,
`kernel-debug.yml`, and `systemd-package-readiness.yml`) accept testing or
compile standards; other workflows require testing standards. Packaging accepts
testing or compile standards, and root Make/DKMS interfaces require compile
standards. Metadata-only changes such as a mode-bit flip do not count as a
standards co-change: the automated applicability guard requires at least one
changed non-whitespace text line in an applicable canonical standards regular
file. A symlink, gitlink, deletion or other non-regular replacement cannot
satisfy the co-change. Review must still confirm the change is semantically
meaningful: textual Git
differences cannot establish relevance by themselves. A later
documentation/report-only follow-up cannot retroactively qualify an invalid
implementation SHA. Failure diagnostics must identify the offending
commit/path, required policy, first error and a safe non-rewriting correction.
Exact-SHA CI requires every prerequisite job to succeed; skipped and cancelled
jobs never count as PASS. The project-goals final result must also fetch the
authenticated current-run Actions job census and require exactly one completed,
successful job for native-rootless, Make interface, each of the three focused
rootless matrix members, and repository policy, plus its own still-running
conclusion job. Match every job to the checked-out source SHA, run ID and
attempt. Verify the checked-out source matches the run SHA before opening
an authenticated network request; a source mismatch must make zero Actions
API calls and refuse locally. Query the attempt-specific Actions jobs endpoint
rather than relying on the run-level endpoint's default latest-attempt
filtering. A missing,
repeated, cancelled, skipped, failed, stale, malformed or additional job, an
unavailable Actions API, or an incomplete response is BLOCKED even when a
subset of other jobs is green. A partial failed-job rerun is therefore
incomplete qualification evidence: after a genuinely transient cancellation
or infrastructure failure, rerun the full required workflow attempt for the
same exact SHA; a reproducible test failure requires a fixing commit and must
not be converted to PASS by repeated retries. CI and test-only edits must
preserve tracked file modes unless an explicit executable-entrypoint contract
requires a mode change; Python fixtures invoked through `python3` do not gain
qualification by becoming executable. A bounded failure-only
refusal identifies the failed gate, required proof, observed classification
and corrective action, without exposing credentials, host paths or unbounded
external text. Keep the native-rootless aggregate required even if the
independent Make-contract job runs the full rootless report-parser regression;
a later successful test cannot hide the earlier failed rootless phase.
Rootless CI is not a substitute for the official source-bound `make test`
report with all five successful stages and final formatter/module/oracle
SHA-256 digests, owner-loaded null_blk qualification, or the separately
authorized physical Linux swap and card acceptance evidence.
The exact-SHA census here-doc must use genuinely empty separator lines, not
indentation-only YAML code-block lines. Verify the committed patch with
`git diff --check HEAD^ HEAD`; otherwise patch-hygiene CI must reject the SHA
even if the Python syntax and synthetic evidence assertions appear correct.

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
stage marker. An explicit primary-lifecycle FAIL takes precedence over a prior
coordinator BLOCKED diagnostic even when a child exits zero. A PASS requires
exactly five ordered PASS stages with integer-zero exits and valid final
formatter/module/oracle artifact digests. An incomplete artifact identity
must return nonzero and remain INCOMPLETE, preserving passed stage observations.
The console cannot advertise loaded service as qualified unless the owner
overall and final artifact identity both pass. Per-I/O benchmark subphase
diagnostics replace the previous subphase instead of accumulating labels:
even a long fixed-source campaign must retain a bounded, actionable failed
phase and the original sanitized failure reason.


### Immutable one-slot lower-I/O qualification

A submitted WRITE run is immutable until definitive lower completion and ordered
publication. Completion callbacks must never observe reused packed bytes,
transaction snapshots, batch hashes, upper-BIO pointers or ordering state.

The rootless `flush-ordering.c` callback/drain matrix must model the current
serialized target order when a fresh upper WRITE arrives after the first terminal
errno is latched but before an older lower run is finalized. While `accepting`
remains true, `->map` may queue that BIO; queuing must not consume or replace the
older lower owner, submit another lower WRITE, acknowledge success, or change the
mapping generation or authoritative extent. The ordered worker finalizes the
older run first, then the queued upper WRITE completes from the first latched
terminal errno without publication. Failure-only diagnostics distinguish
submission, callback and drain phases, callback-observed versus expected completed
blocks, first error, generation, owner and disposition. This finite native schedule
is not a loaded proof that the dm-io callback's context stays valid through its
final queue-lock unlock during concurrent drain.

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
may itself be report-only. After a failed push, bounded retry uses five
noninteractive rounds with 1/2/4/8/16-second backoff and retries transient
fetch/push failures even when origin/main did not move. The retry delay is
isolated behind the reporter's publication-backoff helper so unit tests mock
only the policy delay; they must not patch the process-global `time.sleep`
used internally by subprocess polling. If it
did move, `merge-base --is-ancestor` must prove the tested code revision
remains in current main history. The publisher must then inspect the paths advanced since the tested source.
A Markdown-only concurrent documentation update does not invalidate the tested
runtime source, but any other tracked advance except the generated
`test_results.json` is source-bearing for report publication. When such a
newer source-bearing change exists, the delayed report may be committed only as
an intermediate history record followed by an atomic restoration commit whose
tree preserves the fetched head's canonical `test_results.json`; an older run
must never become canonical merely because it finished later. Rewritten/diverged history,
malformed source ancestry, or exhausted retries fail closed.

Native report-publication tests that create temporary Git repositories must use
`git init --object-format=sha1` (and the equivalent explicit SHA-1 form for
bare origins). The GitHub repository and current report/provenance schema use
40-hex SHA-1 object IDs, so test sandboxes must not inherit an operator's
`init.defaultObjectFormat` or `GIT_DEFAULT_HASH`. Supporting SHA-256
repositories is a deliberate report-schema migration, not a fixture-side
autodetection change.

Publication failures classify only fixed, path-free authentication, remote
policy, non-fast-forward and transport categories. A known noninteractive
credential or remote-policy refusal stops useless retries; transient failures
retain the bounded retry policy. After an HTTPS authentication refusal only,
the publisher may retry once using the existing GitHub CLI
`gh auth git-credential` helper scoped to that invocation, without changing
the owner's saved Git configuration or exposing any token. If this too fails,
the original authentication cause takes precedence, the report stays local
and the console names the owner-side noninteractive credential setup action. Raw Git stderr and credential helper output
must never appear in the public report or console. A failed qualification, or a
failed report push after successful qualification, automatically retains a
private mode-0600 `build/tests/swapz-qualification-failure-*.json` snapshot
containing the tested source, safe failed stage/physical verdict, and bounded
per-round READ coalescing counters. The console prints only its repository-
relative path; the snapshot is never admitted as qualification evidence or
committed to Git. Failure to write it cannot replace the first test failure.

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

The linked production-C lower-write aggregation fixture must also exercise
bounded delayed, zero/partial EIO, successful-short, unsupported, impossible
over-completion paired with a real lower error, and duplicate finalization
sequences. Both the split completion entry point and synchronous aggregation
wrapper must preserve the original lower errno while counting an impossible
completion report as zero credible lower bytes. It must check the explicit
synthetic owner/reference
lifetime, accepted upper writes, final and successful upper completion counts,
single publication, credible completed lower bytes, unchanged original errno,
paused-transaction drain and nonreuse of torn reservations. The duplicate
probe must retain a test-only owner pin while replaying a completed run so it
never dereferences freed storage. Rootless success does not qualify the
loaded dm-io callback-once assumption or actual upper BIO lifetime.


A successful full lower WRITE is also a negative control for partial authority
publication: with valid old mappings, damage only the second paused
transaction's generation while keeping the oldest sequence and complete
physical bytes valid. The production-linked completion must reject it before
publishing the first replacement, leave prior generations unchanged, credit
zero unauthenticated lower bytes, retain all uncertain reservations, and
finish each accepted upper write once with an error. Independently reject a
wrong oldest sequence and altered later run offset; the intact snapshot must
still publish every record once. A mixed compressed/RAW run must additionally
flip only a completed one-block compressed entry's caller-side representation
bit and prove the authority-bound representation rejects it before any
overwrite generation changes or lower-byte credit is recorded. Keep a
test-only pin for a duplicate engine finalizer, not a fabricated second real
dm_io callback or simultaneous worker.

The remaining non-oldest-snapshot boundary must be a production-linked native
regression: keep one test-only owner pin across an actual partial `-EIO` lower
notification and a duplicate finalizer call, while a younger run is paused in
separate storage. Damage a later transaction but not the oldest sequence.
Require zero unauthenticated completed-block credit, no mapping or new
generation, no second upper completion, unchanged younger reservation and
the original `-EIO` rather than cleanup `-ESTALE`. Fail-only diagnostics must
give phase, both sequences, expected/observed blocks and completion owners,
authoritative generations and numeric errno. This does not claim loaded
callback-once or post-release callback evidence.

Source contracts for the immutable-run split must assert semantic ownership,
not retired helper names. Representation-authentication source checks must
require both capture of the authoritative RAW/compressed bit at pause and its
comparison with caller-owned run metadata in whole-run authentication before
replay. The prepare function may test whether a synchronous
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
`memory.current` plus 64MiB. Before allocating ID36 resources,
admission may sample `/proc/meminfo` up to five times over four seconds so
ordinary teardown reclaim can finish; every sample still uses the unchanged
1 GiB `MemAvailable` floor, and the earlier loaded-preflight observation is
diagnostic only. The final admission inventory records canonical kernel-kB
host fields plus the mounted cgroup-root memory controls. A true cgroup-v2 root
legitimately has no `memory.max` or `memory.current` and is recorded as
`root-exempt`; when both files are exposed at a namespaced/non-root hierarchy
root, their canonical values are reported and a finite root must retain the
same 1 GiB effective headroom as the host admission floor. The child's 896 MiB
containment ceiling is not a separate admission threshold. The host must have
at least 1 GiB MemAvailable before this destructive-to-performance but RAM-only
stress begins;
otherwise qualification is BLOCKED rather than silently weakened.

ID36 must classify absent, non-regular, or unreadable child `memory.events`
and `cpu.pressure` files as unavailable telemetry and stop with BLOCKED before
parsing counters. Present but missing, duplicate, malformed, overflowing, or
regressing counters remain distinct invalid-evidence failures. Rootless
resource-admission fixtures cover both unavailable paths and malformed
contents; never convert an I/O or permission error into a counter-format result.

Before the loaded-preflight diagnostic read and ID36 admission sampling,
both scripts resolve the checkout-owned temporary-cleanup helper without an
external `dirname` bootstrap dependency, require it to be readable, and refuse
if sourcing fails. Missing or unloadable helpers block before cleanup or memory
admission: ID36 reports the owned cleanup-helper prerequisite; loaded preflight
uses the structured `LOADED_PREFLIGHT=BLOCKED`
`check=completed_owned_tmp_cleanup_helper errno=unavailable` refusal with a
bounded remedy. Rootless fixtures must prove both refusal paths using only the
isolated bootstrap prefix, without executing privileged preflight or exposing
private paths. After sourcing, loaded preflight handles a nonzero
cleaner return as a named `completed_owned_tmp_cleanup` BLOCKED prerequisite
with the observed helper status. Its completed-owned-only marker follows only
successful cleanup. Rootless contracts must pin that fail-before-evidence
branch rather than require an obsolete shell `||` spelling.

The shared helper inspects the real root-owned mode-1777 `/tmp` and deletes
only positively owned swapz benchmark or deployment sessions with matching
completion proof, an exited owner process, and no same-owner process still
referencing the inspected session directory or files through cwd, root, or an
open descriptor. The existing `make test` loaded-preflight and ID36 admission
invocations automatically sweep both classes, without any additional public
command. Deployment sessions (`swapz-deploy.*`) additionally require one
hour since their most recent directory metadata change, including publication
of the completion marker; the pinned directory identity and mount must be
validated before this age-based retention short-circuit, and the age check
repeats immediately before unlink. A new deployment records the root-owned,
private owner PID and exact source SHA before executing; it writes the matching
completion marker only after safe teardown, successful session-log fanout
drain, retained terminal evidence publication and successful caller-facing
terminal PASS/EVIDENCE publication. A failed caller publication must leave no
completion marker. Rootless producer regressions must inject a caller-output
write failure after the log fanout has drained and a completion-marker commit
failure after caller publication; both must exit nonzero, retain evidence,
withhold a regular completion marker and never validate the failed run as PASS.
The private log must
contain the exact source SHA and one of the three accepted clean-teardown
terminal PASS records directly followed by its pinned session-specific
`EVIDENCE` locator. Legacy deployment logs without explicit matching
owner/completion markers are unverified and never automatically deleted,
even if their text contains PASS.
Unrelated occupants, incomplete/quarantined
sessions, and unproved ownership remain untouched. Unsafe mounts, unreadable
proofs or failed owned cleanup block admission; neither helper broadly empties
`/tmp` or drops kernel caches. ID36 repeats this bounded completed-owned
cleanup after earlier loaded stages, without weakening the 1 GiB
`MemAvailable` threshold.

The matching PID/source markers alone never authorize deletion. A completed
session also requires a private, single-linked `session.log` with the exact
source SHA in its initial 4 KiB and the producer's successful ordinary-teardown
record followed by the exact terminal
`EVIDENCE=<pinned-session>/session.log` line in its final 4 KiB. Reads must
remain descriptor-pinned, same-mount and bounded independent of log size. The
evidence path is derived from the pinned session descriptor, not caller path
text, so a same-source PASS log copied from another session is not provenance.
Marker and evidence-file identity metadata must remain stable across their
reads. Missing, mismatched, replaced, unstable, or nonprivate proof retains the
session. This is same-owner corroboration, not cryptographic attestation
against a privileged actor able to forge both markers and logs.
An equal-size in-place marker rewrite may leave mtime and ctime unchanged
on coarse-timestamp filesystems, including observed F2FS cases. Marker proof
must therefore compare two bounded reads from the same pinned descriptor as
well as its original metadata; changed-content samples retain the session
even when the metadata looks stable. Identical-byte rewrites do not prove
content mutation and may be indistinguishable when timestamps remain stable.
Each pinned double-read is not atomic against a deliberate same-UID actor who
rewrites and restores bytes between its observations. Inspection and live-use
checks also occur after the initial ownership proof, so cleanup must repeat the
full bounded owner/completion/evidence/PID proof after the activity inventory
and immediately before the first unlink. A persistent changed owner or
completion marker must retain the session even when its identity metadata and
timestamps appear unchanged; an identical-byte rewrite remains
content-equivalent. This final reproof narrows the authorization window but does
not claim atomicity against a same-UID actor that changes and restores bytes
after the final observation. Rootless regression must cover synthetically
stable timestamps with changed marker content (fail-before / pass-after),
native timestamp behavior, identical-content rewriting, and persistent
post-proof owner/completion rewrites; repeat on tmpfs, and report unavailable
F2FS execution separately.

Inspection and removal must revalidate directory owner/mode plus regular-file
owner/mode, single-link state, size and change timestamps before unlink. A file
that grows, is hard-linked, changes owner, or otherwise changes after the
bounded inspection is ambiguous state and blocks cleanup rather than bypassing
the inspected resource bound. Keep the teardown log and owner/completion
records until scratch removal ends; after proof removal, a failed final rmdir
leaves non-resumable retained state, never a fabricated cleanup PASS. Rootless
native fixtures must cover foreign occupants, symlinks, hardlinks, metadata
changes, substitutions, interrupted removal, unreadable entries, and injected
unlink/rmdir/close errors. Before the first unlink, revalidate that the root
pathname still identifies the original pinned root and reopen the named session
without following symlinks to confirm its original device/inode/owner/mode and
mount ID. A root or session rename, replacement, or remount during the bounded
inspection must block with no deletion. After that pathname/mount revalidation
and before the first unlink, perform a bounded same-owner /proc inventory and
retain the session if any process or live worker task still references an
inspected session object through cwd, root, an open descriptor, or a live
file-backed mapping. Check the cleanup process's inherited cwd and root
separately before skipping its own PID; its intentionally pinned cleanup
descriptors are not activity evidence, but an inherited cwd/root inside the
session is. Inspect non-leader /proc/<pid>/task/<tid> cwd/root/fd views as well
as the thread-group leader because Linux may leave the leader visible as a
zombie while live workers retain resources and the leader fd/maps views are
empty. A bounded maps scan matches mapping device/inode without using private
path text, including when the process has closed its file descriptor; once a
nonempty thread-group mapping inventory is visible, duplicate task maps need
not be rescanned because threads in that group share the address space.
Unreadable or malformed mapping inventory for a confirmed same-owner process
or live task blocks cleanup; original I/O errno must remain available. Failure
to enumerate /proc or a confirmed same-owner process's task inventory, or to
prove the owner of an enumerated process/task, is uncertainty and blocks
cleanup. Only disappearance evidence is skippable: a vanished process, vanished
task, closed descriptor, or process/task that exits during the scan may produce
FileNotFoundError and be treated as no longer observable. An empty leader view
alone is not disappearance evidence while a non-leader task remains visible. Permission denial on
a confirmed same-owner process's cwd, root, descriptor inventory, individual
descriptor, or mappings is activity uncertainty and blocks cleanup. Do not
treat EACCES as process exit or as proof that the process is unrelated; until
those references are readable enough to exclude the inspected session
identities, deletion authority is unproved and the safe action is read-only
review. In the owned-RAM recovery helper's task-specific
`/proc/<pid>/task/<tid>/mountinfo` scan, an `EINVAL` read may be treated as a
vanished mount view only after the same task's
`/proc/<pid>/task/<tid>/stat` is read successfully, its parsed task ID matches
`<tid>`, contains the numeric start-time field, and its state is exactly `Z`.
A malformed, truncated or inaccessible stat record,
an identity mismatch, any non-zombie task, or any other mountinfo errno remains
a refusal with the original error preserved. This narrow procfs case does not
apply to the production primary manager's mount inventory or malformed
mountinfo parsing. Rootless regressions must prove zombie `EINVAL` is skipped,
live-task `EINVAL` and non-`EINVAL` errors remain failures, and malformed or
substituted task-stat evidence is rejected. Native rootless tests independent of procfs visibility
must substitute a deterministic, explicitly named process inventory only within
the test interpreter, never through the production cleaner's environment or
command-line. Register each real live FD or mmap fixture holder so its actual
procfs cwd/root/fd/maps evidence remains subject to the normal activity check.
Retain separate permission-denial controls for an enumerated live holder's
cwd/root, descriptor inventory/entries, and maps, plus unknown process
ownership, verifying the original EACCES, phase, disposition and read-only
remedy. Synthetic cwd/root inode observations may
cover unprivileged fixtures, but production must retain the real cwd/root scan.
Never classify an arbitrary protected runner process as exited or treat a
failed relevant mapping read as proof of inactivity. Diagnostic refusal must
identify the observed uncertainty without exposing private paths.
The same-owner provenance model already does not defend against a same-UID
actor deliberately forging the
markers and evidence. Keep the independent final session identity check before
rmdir; these checks do not claim atomicity against a privileged same-UID actor
concurrently mutating private directories.

On refusal, the private helper emits the session class, validation phase,
category, ownership/identity disposition, original errno (when present) or
process exit code, prior fully removed count, conservative retained-state
disposition and read-only safe next action, without echoing paths or PID
inventories. The first
operation error takes precedence over secondary descriptor-close failure.
Successful output is a single bounded aggregate of completed removals,
unproved retained candidates, identity-rejected candidates, active-use and
recent-age retained candidates, and logical bytes unlinked by fully removed
sessions, never per-entry success chatter. Logical
file bytes are not a claim of immediate physical or tmpfs RAM release: sparse
files and still-open descriptors can make actual reclamation differ. A failed
or partial session never contributes to successful reclaimed-byte totals. The existing
external 30-second watchdog bounds the caller's wait under normal scheduling;
a journal-blocked uninterruptible syscall may outlive a kill signal, so the
watchdog is not proof of a strict kernel-side I/O deadline.

The owned pair first creates and fully faults both 64MiB memory-backed
`null_blk` devices outside the ID36 cgroup. It then migrates its benchmark
process into the cgroup, proves that membership, and stops at a private barrier.
After publishing its readiness PID, the pair shell stops itself with SIGSTOP;
this avoids polling with an external `sleep` process that would briefly join
the cgroup and violate the exact one-PID pre-pressure invariant. The parent
binds the nested readiness process to the captured outer-timeout identity and
its own start time, waits until it is stopped, and verifies the exact cgroup
membership before starting pressure. After pressure is active and the private
release marker is written, the parent resumes only that captured process
through its pidfd. If identity or resume state is uncertain, the pair and
private cgroup remain quarantined for investigation.
At this pre-pressure barrier, `cgroup.procs` must contain exactly the pair's
canonical readiness PID and no other process; the pressure helper has not been
launched yet. Any additional canonical PID is ownership contamination and
BLOCKS admission. Cleanup may terminate only directly tracked owned children
and must retain the contaminated child cgroup plus private scratch for read-only
investigation; it must not use `cgroup.kill`, `rmdir`, or recursive scratch
removal on that refusal.
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

The rootless ID36 cleanup-ownership fixture executes extracted production
helpers against synthetic cgroup and private-session files, never real cgroups.
When simulating a reaped readiness child, keep its previously admitted pair PID
in the fixture: a different PID is foreign membership rather than stale.
Assert with a live foreign process plus a separately owned direct child that a
member appearing between two membership snapshots is never signaled as owned
and never authorizes cgroup.kill. Delayed departures require a fresh empty
snapshot, and any refusal must describe the actually retained resources and
earliest failure. Private-session cleanup must snapshot the validated canonical
names and unlink only that snapshot; a canonical name injected after inventory
must remain present and force the final rmdir refusal. A session-signal refusal
retains both created resources; after successful cgroup removal, session-only
refusal retains only the private session.
A final `rmdir` failure on an otherwise emptied private session, or a
same-name directory replacement after successful final removal, is a
session-only refusal. Rootless fixtures must independently inject both, verify
the original exit and first refusal phase, prove the failed removal retains the
original device/inode while post-removal path reappearance has a different
device/inode, retain the remaining session-path obligation, and prohibit
synthetic ID36 PASS evidence.

After a post-mkdir cgroup pin or identity refusal, the rootless fixture must
inject missing directory-fd authority, unreadable created-directory identity,
and mismatched pinned/name identity. Each case must retain both resources,
report only the originating `phase:cgroup-create` (not a second
`phase:prior-admission`), keep the actual original status including 143,
label nested resume as not required, and never signal or claim ID36 PASS.
Extract and execute the production session/cgroup descriptor-open commands
against missing synthetic private paths; require Bash's open failure to expose
no path text, require a successful grouped open to retain its descriptor, and
require stderr to be restored for the following bounded diagnostic.

Rootless ID36 process-identity negative controls must distinguish a missing
readiness child from `timeout-parent-gone`,
`timeout-parent-start-changed`, `readiness-child-reparented`, and
`readiness-child-start-changed`. The production identity helper must use
both exact pidfds as liveness proof around numeric `/proc/<pid>/stat` reads;
start time and PPID text alone are insufficient PID-reuse authority. An exited
timeout with a live reparented pipe-held readiness child is **ambiguous
ownership**, not child-exited success: preserve the first failure/status, do
not send PID-number signals, retain both created resources, and report the
bounded identity category rather than an opaque numeric helper status. The
same real rootless probe must reject changed parent and child start times. A
changed-child-start regression must provide a decimal, nonzero value different
from the captured child start tick so it reaches the identity comparison and
expects status 8 (`readiness-child-start-changed`); zero is malformed telemetry
and must be rejected earlier with status 2, not mistaken for a pidfd or
timeout-parent status. When an identity status differs from the expected one,
the fixture diagnostic should include both numeric and symbolic actual status.
The launcher must publish the child PID atomically through a sibling temporary
file and rename: file existence can become visible before direct writes have
filled the file. The reader must accept only a complete positive decimal PID
within its bounded wait, and release the grandchild by closing the owned pipe,
not by signaling an orphan or treating an empty/partial marker as process
identity evidence.
The focused negative controls must also exercise status 3 with an actually
exited nested child while its captured parent remains live, and status 7 with
a live stopped exact child whose observed PPID is synthetically changed after
both exact pidfds have opened.
The status-3 launcher must use its directly tracked external Python parent
rather than infer creator identity from nested-shell `$$`; the fixture heredoc
is that parent's source stdin and must not be overridden by another stdin
redirection. Failure to capture the parent identity is a bounded fixture
precondition failure, not evidence for status 3.
The parent release fallback must remain strictly inside the fixture's outer
subprocess timeout while leaving scheduling headroom for the extracted identity
helper calls; scheduler delay must not become an early parent-exit false negative.
The status-7 signal attempt must refuse before SIGCONT and prove the exact child
remains stopped; neither mismatch may be treated as cleanup authority.
Keep the status-3 and status-7 controls in separate bounded fixture invocations
so one identity boundary cannot consume another control's subprocess deadline.
A stopped-child fixture must publish its own shell PID with `$$` verbatim
before SIGSTOP; a truncated shell PID token is malformed fixture evidence.
Successful synthetic cleanup prints only a
`ROOTLESS_FIXTURE_ID36_CLEANUP` marker, never an actual
`PASS_ID36_RESOURCE_PRESSURE` token.

ID36 sets its child cgroup's `memory.swap.max=0` and requires canonical
zero `memory.swap.current` before pressure and after the pair. That proves
only zero sampled swap charge for memory owned by that child cgroup under a
zero swap limit. It is **not** a host-wide no-swap or "RAM-only" proof: Linux
keeps existing memory charged to the cgroup that instantiated it when a
process later migrates, and host `/proc/vmstat` pswpin/pswpout includes
unrelated activity. `memory.events high` is reclaim pressure, not swap.
Therefore `PASS_ID36_RESOURCE_PRESSURE` remains memory.high/CPU-PSI pressure
evidence only. A loaded anonymous-swap claim instead requires a fresh owned
workload cgroup with a validated zero baseline, positive
`memory.swap.current` at the swap-out evidence point and non-regressing
`memory.swap.peak`, exact mapper `/proc/swaps` usage attributable to that
charge, swapz/lower WRITE and READ activity, vmstat pswpout/pswpin only as
corroboration, host-memory safety samples, no cgroup OOM or unexpected
termination, successful terminal worker exits and the byte-exact oracle.
Synthetic fixture output cannot replace any of those observations.

**Codex agent A and Codex agent B: mandatory loaded anonymous-swap cgroup
setup/teardown handoff (neither is authorized by rootless ID36 fixtures).**
Before starting pressure, each agent must establish all of:
(1) cgroup v2 mount/root provenance, delegated memory/CPU controls and an
authorized writable parent; no host-wide controller or swap changes;
(2) a uniquely created private child and private scratch with pinned
directory descriptors, matching named-path device/inode and no symlinks;
(3) present, readable `memory.max`, `memory.current`, `memory.swap.max`,
`memory.swap.current`, `memory.events`, `memory.pressure`, `cpu.pressure`,
and `cgroup.procs`, with a finite safe memory budget and an explicitly
permitted nonzero swap budget (not ID36's swap.max=0);
(4) canonical empty initial membership, baseline counters, two successive
whole-host MemAvailable observations at or above 1 GiB, and sufficient
validated effective parent headroom;
(5) Popen/direct-child or equivalent durable owner handles with captured
PID, PPID, start time and pidfd binding **before migration**, then exactly
the admitted workers and no foreign members before FILL;
(6) bounded pressure/PSI, memory-available and OOM monitoring plus a
zero workload-cgroup swap baseline; at FILL require positive
`memory.swap.current`, non-regressing `memory.swap.peak`, and exact mapper
`/proc/swaps` usage attributable to the cgroup charge; require target/lower
WRITE then READ activity, use vmstat pswpout/pswpin only as corroboration, and
finish with terminal worker exits plus the byte-exact oracle.
During teardown, each agent must (7) cooperatively stop and boundedly reap
the same proved workers, using TERM/KILL only through revalidated pidfds for
positively identified processes; never signal guessed/reparented/reused PIDs
or use `cgroup.kill`; (8) prove every admitted child exited, verify two fresh
canonical empty membership observations and the same pinned/named cgroup
identity, then ordinary `rmdir` only; (9) inventory/unlink only pinned,
canonical regular scratch entries and nonrecursively remove its verified
directory. Any missing identity, retained child reference, foreign member,
nonempty/unreadable membership, changed path inode, telemetry regression or
cleanup failure means BLOCKED and retained evidence, with phase, expected
proof, observed category, whether signaling/removal was attempted and original
exit status. The agents must not claim loaded-host swap qualification from
rootless synthetic observations, vmstat alone or an oracle without actual
cgroup swap charge.

The nested-child resume cleanup guard must interpret the numeric uncertainty
state arithmetically: zero permits an attempt only with the existing tracked
timeout, captured readiness PID, and captured nested process identity; one
skips SIGCONT and quarantines the private cgroup and scratch. Rootless tests
must first reproduce the original nonempty-string negation failure for both
zero and one, then execute the extracted production cleanup with a real
stopped timeout child and checked parent/child start-time identities. Confirm
pidfd SIGCONT and bounded direct-child/session cleanup for zero; for one,
record the verified stopped state before cleanup and confirm no nested signal
or explicit timeout termination (the bounded timeout may later exit naturally),
a live foreign process
survives, and both uncertain resources remain. Inject identity-bound wait
and SIGCONT failures to verify one bounded attempted-versus-skipped diagnostic
and that the original EXIT/signal status wins over subsequent cleanup failure.
If an earlier admission or cleanup refusal already owns that bounded cleanup
diagnostic, later wait, SIGCONT, child-stop, cgroup or session failures may
strengthen retention but must not emit a second cleanup phase; first-error
attribution remains stable. Ordinary cleanup-refusal diagnostics must
also state the nested-resume disposition (`not-required`, `attempted`,
`prohibited-unproved` for incomplete nested identity, or
`skipped-uncertain`), the failed ownership proof and bounded
expected/observed state, preserved `original_exit`, precise
`retained_cleanup` class, and the safe
`next_step:read-only-review-retained-state-before-retry`. Classify the nested
disposition before any stop-marker refusal can be reported; a partial proof
never grants SIGCONT or wider cleanup authority. If a tracked timeout is still
live after its readiness marker is published, or after the readiness PID is
copied but before the nested identity is proved, cleanup must mark resume
uncertainty before direct-child teardown, report
`phase:pair-resume observed:prohibited-unproved` unless an earlier failure owns
attribution, and retain the child cgroup plus private session. Existing final-directory replacement and
rmdir-failure regressions still prove
first refusal and remaining session ownership; no cgroup.kill or loaded host
pressure cleanup is permitted by these rootless proofs. A repeated HUP/INT/TERM
during EXIT cleanup must not abort the remaining ownership-checked teardown
or replace an already failing original status (including 143) or prior cleanup
refusal. The EXIT trap must capture the entry status and mark cleanup active
before calling the cleanup function, so a signal arriving before its local
signal traps are installed is latched rather than terminating teardown. The
global-to-local trap handoff must use the same first-signal latch: a later
signal after local installation cannot replace an earlier pending signal. If
cleanup began successfully, the first such signal supplies its
129/130/143 status, suppresses PASS even if both resources are removed, and
produces one path-free cleanup-signal diagnostic with proven ownership,
resumption and exact retention. If that signal precedes a later cleanup
refusal, the public phase remains cleanup-signal; the delayed diagnostic records
the bounded refusal and whether both resources or only the private session
remain. Inject TERM at the synthetic cgroup rmdir boundary for both a retained
refusal and a fully removed session, and at final session rmdir for session-only
retention.

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

The timed packed-read evidence uses a deterministic, ascending six-page
population group followed by `fsync`, outside the read timer. This matches the
existing six-record/four-block pack-ready geometry and lets each group commit
before the next logical range is submitted. Both fast-model ID63 arms enable
the same write-admission read-cache invalidation, so stale prefill/mixed-read
cache entries do not stand in for lower READ traffic. The sequential and
seeded-random byte oracles remain unchanged, and every merge-on sequential
round must still record at least one successful adjacent lower READ merge.
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
262,144, 1,048,576, 4,194,304 and 27,080,192 logical pages. These represent
1GiB, 4GiB, 16GiB, and the current authorized card's maximum logical capacity
at 4KiB/page (1,024, 4,096, 16,384 and 105,782 physical segments). It reports
four CPU-only timings: the retired full-map score rebuild, current per-segment
victim selection, legacy full-map relocation ownership discovery, and ID61b
per-segment-list relocation of the same 256 survivors. Timing is directional
CPU evidence, not a physical-media latency claim. The sanitized report must
retain all four rows.
The final row follows the currently authorized card geometry and must be
updated if that target changes. Loaded qualification must additionally prove that
successful GC visits exactly `gc_pages` relocation-list entries, rather than
merely timing a native surrogate. Report `85aeac4` satisfies this production
gate with 20 relocation-list visits for 20 relocated pages,
`gc_choose_map_entries=0`, 20 victim rotations and byte-exact verification of
all 4,096 logical pages. Keep the full-map relocation path only as the portable
fallback when the segment-membership sidecar is absent.

The native tests can run concurrently under an inherited GNU Make jobserver,
but their structured evidence markers are line-oriented records consumed by
the official reporter. `tests/tools/test-rootless.sh` must invoke the native
Make stage with `--output-sync=target` so sibling target output cannot
interleave and corrupt a marker. Keep the evidence parser strict; do not accept
embedded or partially interleaved records as valid evidence.


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
dead-segment scan with mapped-page fast rejection at the four required
geometries above, including current-card logical capacity. Production-C fault
injection must forge indexed empty-segment
views (mapped count, physical liveness, reverse-list headers and GC costs)
while retaining authoritative logical maps, then additionally clear the
extent-class bytes and the segment-open count. The candidate must still reject
reuse before the recycle hook, role change, generation change or new mapping
publication; neither an apparent virgin program count nor any other false-zero
sidecar may waive the independent authoritative-map proof.

A separate production-C case must forge a closed segment into an apparent
single-mapping state while retaining a second authoritative map with zeroed
liveness/class sidecars. Discarding the apparent final page must return
`-EUCLEAN` before authority mutation, so the DM early whole-segment TRIM path
cannot erase the stale live extent. Full-map proofs remain confined to
irreversible reclaim, normal role exchange and closed-segment final-map
transitions; they must not enter ordinary open-segment allocation/publication.
Loaded qualification still requires the full zero-mapped candidate liveness
scan, repeated live-GC correctness, exact readback, and nonfatal DISCARD
semantics.

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

### Core-2 two-choice first-data-block cache and copy avoidance

The legacy-named `read_metadata_cache` is not metadata and never reconstructs
swapz authority from media. It keeps exactly 512 immutable first 4KiB
extent-data payload blocks; mapping, generation, CRC, offset/length, sequence
and GC authority remain bounded RAM state elsewhere. Its directory is 128 sets
by four ways. Each tag is exactly 16 bytes and each four-way set starts on a
64-byte boundary. Each key has two distinct hashed set choices. Search primary
first and inspect secondary only after a primary miss: at most two tag
lines/eight tags. A 512-entry fallback scan or separate direct front is not
permitted. Replacement chooses an invalid way before the oldest tag across the
two candidate sets. Complete invalidation before authority mutation remains
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
4096 bytes into read scratch merely to decode one record. Metadata-only
descriptor decode must not synthesize a payload pointer beyond the resident
block-zero image; callers that only need descriptor fields pass no payload
output pointer. If the selected payload overlaps block zero, copy only that
exact payload fragment; CRC validation must cover the reconstructed contiguous
payload and remain bound to the separately validated metadata/authority identity.
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
Source ordering must place this ACK-only barrier before both synchronous
success ACK and detached-run lane-success/upper-completion publication or defer
delivery. It does not delay authority replay from an already completed immutable
RAW lower write; generic/preempt-disabled completion paths must not sleep. Prepared and ordered owners are separate
required cases; the ordered mapped-input case must prove unmapping precedes the
error return. Positive and zero controls must continue to select compressed and
RAW storage respectively.

Direct codec qualification must include deterministic nonzero randomized
payload bytes, boundary lengths around 8-byte/CRC lanes and production packing
cliffs, the maximum accepted payload, deliberately unaligned extent/payload
addresses, and every stored encoding. These cases supplement, rather than
replace, the full-page structured/entropy predictor corpus and independent
scalar/SIMD transform/shuffle oracles. A metadata-CRC-only descriptor lookup
must reject zero generation and payload offsets inside the metadata envelope,
even when the forged payload checksum also matches; callers retain responsibility
for full descriptor order and mapping identity.

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

### Legacy SWZ codec compatibility (non-production)

SWZ identifies the internal 4/8/16KiB packed-extent design, not a physical
backing format. The only permitted physical partition signature is the
pre-existing SWAPSPACE2 header. Production compressed WRITE, READ, publication
and GC authority use data-only lower extents plus bounded RAM descriptors.

Historical `SWZ\\0` header/descriptor encode-decode helpers may remain only
as isolated compatibility/unit-test code. They are not production I/O
authority, cannot authorize a raw device, and must never be used as a template
for a new partition header or persistent swapz metadata. Production-facing
fixtures must inspect RAM descriptor authority and data-only extent boundaries.

## ID73 CPU/cache qualification

`make test` and `make test_full` are the two source-bound public tiers;
the runner derives bounded compilation parallelism or inherits the Make
jobserver, and neither tier skips native CPU/cache correctness. The native
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
Rootless qualification must prove the removed raw-partition formatter cannot
reappear through current lifecycle code. Exercise the primary admission path
with synthetic descriptor/kernel operations for PARTUUID, geometry,
physical-parent identity, exclusive-open state, mount/swap inventory and the
immutable 4096-byte SWAPSPACE2 block-zero digest. Every refusal before mapper
creation must leave block zero byte-identical and perform zero raw writes, zero
raw fsyncs and zero raw formatting. Fault injection belongs on mapper/module/
swap activation, payload-only lower I/O and durable lifecycle-state publication;
there is no torn-header-write recovery case in the current design.

The PARTUUID direct-C coverage retains malformed selectors, alias replacement,
parent/geometry drift, holder/activity, read-only transition, mount/swap
inventory and reconnection-repinning checks without opening a host block
device. Source contracts must prove no public or private new-run path contains
a raw-partition formatter or block-zero write primitive. Historical formatter
diagnostic strings may be parsed only as legacy evidence and must never be a
requirement for current source.

A physical ordinary-swap development trial is reached only after the exact
current source completes the RAM/loaded qualification stages and the private
handoff supplies source/artifact-bound evidence. The privileged helper may set
the immutable physical RAM-metadata qualification token only after validating
that evidence. Noninteractive qualification never discovers, prompts for or
writes a physical device.

#### Development-only ordinary-SWAPSPACE2 trial

The development trial accepts only an already formatted ordinary Linux
`SWAPSPACE2` partition selected by stable PARTUUID identity. Its raw header,
UUID and partition table are immutable. No current path may clear or replace
block zero, publish `SWAPZ001`, run `mkswap` on the raw partition, or use
saved bytes as permission to repair/reformat it. Before mutation, revalidate the
exact partition, geometry, parent topology, active-swap inventory, memory
headroom, mapper/module ownership and current-source artifacts. Use ordinary
`swapoff` only for the explicitly selected target; never use `swapoff -a`.
After swapoff, prove the raw partition inactive and byte-compare block zero with
the preflight digest before mapper creation.

Current trial admission is scoped to the selected ordinary swap partition, not
to an obsolete formatter-wide host state. Never require the global
`/proc/swaps` inventory to be empty merely because other Linux swap is active.
A selected partition with nonzero `Used` remains admissible after exact
header/geometry/identity checks; immediately before its owned `swapoff`, require
bounded `MemAvailable` headroom for those live pages. Unrelated swapfiles remain
active and identity-checked, and `swapoff -a` is forbidden. Source/native
contracts must reject any return of the retired
`require_development_formatter_inventory_clear` / `formatter_inventory`
admission gate.

The Device Mapper target reserves physical block zero and exposes only the
aligned post-header data region. All swapz mapping, extent/record descriptors,
generation/sequence, CRC, payload offset/length, allocator and GC authority
remain bounded RAM state. The lower data region contains payload bytes and
deterministic zero padding only. The newly created mapper alone may receive
`mkswap`. The bounded anonymous-pageout oracle must independently prove
positive exact-mapper Used KiB and positive lower WRITE bytes. When either
proof is missing, the official failure must name the first missing gate and
report bounded numeric observations for both counters; an advisory
`MADV_PAGEOUT` return or zswap-retained page is not lower-device evidence.
Rootless negative controls must keep both refusals distinct without altering
the positive proof or allowing a physical qualification PASS.
On successful completion, preserve the user's same-boot choice:
keep the verified swapz mapper active or stop it and reactivate the unchanged
ordinary swap partition at its recorded priority. No reboot is required.

The production-readiness evaluator must also bind the CURRENT release-host
platform to the owner qualification: x86_64, 4096-byte pages, and an exact
well-formed `kernel_release` matching the owner `make test_full` RAM report. A kernel
upgrade or platform mismatch makes the release BLOCKED until fresh owner
qualification and downstream exact-source evidence are regenerated.

The primary manager's rootless swap-inventory parser tests must cover the
signed priority endpoints INT_MIN/INT_MAX, reject malformed or overflowing
tokens, and preserve the observed output on failure before any raw swapoff.

The primary manager's PARTUUID direct-C tests must reject all-hyphen,
leading/trailing-hyphen and consecutive-hyphen values, require at least eight
hexadecimal digits, preserve GPT-style hyphenated values, and prove canonical
lowercase normalization. This is a Codex-owned integration requirement; the
standalone formatter tests do not authorize edits to primary-manager source.

The standalone CLI requires the complete partition/PARTUUID/geometry/removable-
parent identity bundle documented in coding_standards.md. Linux may omit a
`slaves/` directory on a physical partition sysfs node; the formatter treats
only that absent partition-level directory as empty after rechecking that the
partition sysfs object still exists. Errors other than `ENOENT`, a present but
unreadable/non-directory entry, and any nonempty `holders/` or `slaves/`
directory still fail closed. Parent `holders/` and `slaves/` directories remain
mandatory and must be empty. Partition `holders/` remains mandatory; partition
`slaves/` must be empty when present. The older private
physical-swap correctness probe remains historical machinery; do not relax the
standalone formatter or repurpose that helper for production lifecycle
activation merely to preserve its former formatter argument list.

A physical ordinary-swap development trial is reached only through the
interactive algorithm-tier handoff after the exact current source completes
the five RAM/loaded `make test` stages. The handoff supplies a private,
nonce-bound evidence record containing the tested source and artifact digests;
the privileged helper must validate that record before it can set the kernel's
immutable `physical_ram_metadata_qualified=1` module token. Noninteractive
qualification never discovers, prompts for, or writes a physical device.

#### Development-only ordinary-SWAPSPACE2 trial

The development trial accepts only an already formatted ordinary Linux
`SWAPSPACE2` partition selected by stable PARTUUID identity. The raw partition
header, UUID and partition table are immutable. No current path may clear block
zero, publish `SWAPZ001`, run `mkswap` on the raw partition, or use a saved
header as permission to repair/reformat it. Legacy SWZ-header parsing in the
private helper exists solely to recognize historical interrupted
pre-migration journals and must stay unreachable from new-run mutation.

Before mutation, revalidate the exact partition, geometry, parent topology,
active-swap inventory, memory headroom, mapper/module ownership and
current-source artifacts. Use ordinary `swapoff` only for the explicitly selected raw
partition; never use `swapoff -a` and never deactivate unrelated swapfiles for
a swapz trial. Unrelated regular swapfiles may remain active when their saved
inode, size and priority identity is stable; the run must not claim ownership
of their activation state. The RAM-headroom calculation therefore covers only
live pages on the selected raw partition that Linux must migrate during its
exact-device `swapoff`. After `swapoff`, prove the raw partition is inactive,
prove admitted unrelated swapfiles remained active and unchanged, and
byte-compare the raw partition's first 4096 bytes with the preflight image
before creating the mapper.

The Device Mapper target reserves physical block zero and exposes only the
aligned post-header data region. All swapz mapping, extent/record descriptors,
generation/sequence, CRC, payload offset/length, allocator and GC authority
remain bounded volatile RAM state. Lower storage contains compressed/RAW
payload bytes plus deterministic zero padding only. Preserve 4/8/16KiB
packing, overwrite ordering, DISCARD, GC, short/error I/O handling and
byte-exact readback.

Only the newly created run-owned mapper may receive `mkswap`; activate that
mapper with `swapon` for the bounded real anonymous-page round trip. A
successful trial must ask the operator whether to keep the verified swapz
mapper active or return to ordinary Linux swap. Choosing restore removes only
run-owned mapper/module state and reactivates the unchanged raw partition at
its recorded priority. No reboot is part of either transition.

Durable state for crash-safe session ownership may record target identity,
source/artifact identity, original swap activation/priority, mapper ownership
and teardown progress. It is lifecycle state, not swapz extent metadata and
must never become a new on-partition format. New-run recovery must treat a
changed block-zero image as a hard failure requiring read-only inspection; it
must not rewrite block zero. Historical pre-migration recovery compatibility
must remain explicitly separated and may not be generalized into the normal
lifecycle.

Native/rootless coverage must prove that new runs cannot reach any raw-header
writer or legacy SWZ formatter, that mapper `mkswap` targets the exact
run-owned DM device, that physical offsets exclude block zero and unused tail,
and that failures before/after swapoff, mapper creation, activation, I/O and
teardown preserve ownership and fail closed. Loaded RAM qualification must
exercise payload-only compressed WRITE/READ, overwrite, DISCARD, GC,
corruption/short-I/O rejection, concurrency and target recreation before a
physical development handoff is admitted. Physical development evidence is
not production qualification or physical-media endurance evidence.

### Alpha.29 work-conserving dispatcher qualification

Both public qualification commands retain native correctness; `make test_full`
adds rootless integration. Native qualification exercises
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


The dedicated native `preparation-publication-lifetime` regression executes the
production preparation-slot helpers in both deterministic state-publication
orders. Its 2,048 handoffs per run cover compressed success, no-fit RAW, exact
negative errno, RAW_SELECTED racing a late negative result, result-ready ACK
gating, the last producer/consumer reference, slot-63 reclamation and reuse,
and closed-admission wake suppression. For producer-won READY_COMPRESSED, READY_RAW and ERROR, the consumer
must acquire the actual preparation state and validate length, exact errno
and compressed bytes before any `result_ready` acquire or post-publication
pthread barrier. A relaxed scheduling gate pauses producer completion until
those checks finish, so an unrelated completion cannot hide a broken state
publication. RAW_SELECTED leaves the state unchanged: that consumer must instead
acquire the modeled `result_ready` completion before reading its late result.
Historical BIO acknowledgements are target-side completion state and are not
modeled by this preparation helper regression.
The C11 shim remains a race-test model, not a Linux memory-model proof or a
substitute for loaded target, suspend/drain, completion-work and lower-I/O
fault qualification.

The cancellation/lifetime continuation runs 384 three-party handoffs with
bounded synchronization barriers. It follows the production terminal-failure
states rather than treating RAW selection as cancellation. Worker-first cases
publish READY_COMPRESSED, READY_RAW and exact ERROR. The compressed READY is
retired to CONSUMED before the worker put, READY_RAW is retired after the worker
put, and ERROR remains ERROR until the ordered final-put. Cancellation-first
cases retire PREPARING to CANCELLED before delayed compressed, no-fit RAW and
negative codec results; each late worker publication must observe CANCELLED and
the worker is final-put. Non-error workers model the production ready-reservoir
charge before publication: a CANCELLED loser rolls it back, while a READY result
is charged exactly once until terminal retirement consumes it. Every epoch
asserts one PREPARING terminal claimant, one worker result attempt, one final
reference release, zero ready charge at drain, no pre-drain slot claim, and
slot-63 reuse only after both ordered and preparation completions. Ordinary
result metadata and compressed bytes are read only after the production state
acquire while the ordered owner still holds its reference; after an early
cancellation put, that owner observes only atomic audit fields. Reclaim poisons
old result metadata and bytes so the next compressed generation cannot validate
stale payload, and checks that no late publisher runs after the last release.
On failure, report the worker/completion phase, reference transition, slot
state/mask, ready charge, expected terminal/final owner and actual transition;
never print page payload bytes. These finite C11 schedules remain supporting
evidence, not loaded KCSAN, lockdep, or proof of kernel execution under
suspend/drain.

The shutdown-overlap continuation runs 32 deterministic rootless schedules with
three simultaneously live owners: an in-flight lower callback, deferred
completion work and a cancelled preparation producer. A fourth drainer closes
admission and joins those three pthreads. The schedule separately exposes
lower-callback return, completion_active clearing, the producer's final
prepared-slot put and slot-63 reuse before allowing the completion and producer
threads to return. The modeled allocation may become releasable only after all
three joins and only with zero active owners, zero prepared references, an EMPTY
slot and the free-mask bit restored. Late compressed, no-fit RAW and negative
codec results all lose to CANCELLED. This test is lifetime-ordering evidence for
the rootless model only; it does not model dm_io/workqueue internals and does
not upgrade sanitizer results into loaded-kernel race freedom.

The preparation-slot helper regression must not manufacture concurrent
`swapz_preparation_retire()` and `swapz_preparation_consume_ready()` calls
for one prepared page and describe that as a production ownership transition.
They are alternative actions of the single serialized ordered owner: the normal
ordered path consumes READY, while terminal completion retires PREPARING/READY;
the asynchronous preparation worker only publishes its result and drops its own
reference. Production-faithful rootless schedules instead race that one ordered
owner against producer publication and producer final-put. The dedicated
cancellation/lifetime continuation covers PREPARING -> CANCELLED when failure
wins, READY -> CONSUMED when publication wins, ERROR remaining ERROR, both
possible final-reference owners, slot-63 reuse only after the last reference,
and stale-payload rejection after reclaim. A generic helper-contention test may
be kept only when explicitly labeled non-production and must not count as BIO
completion-ownership evidence.


The submitter-path continuation adds 256 deterministic handoffs that model its
release/acquire active-descriptor gate, one-reference prepared page, separately
leased scratch lane, exact error and a closed admission gate. Its scheduling
flag is deliberately relaxed: the ordered owner reads ordinary payload after
acquiring `preparation_submitter_active == 0` and before any synchronizing
pthread barrier, so the test actually depends on the production release/acquire
ownership edge. Even when the BIO has completed and its page slot is free,
drain cannot finish until the submitter has released its scratch lane. This
is a C11 lifetime model, not proof of the kernel target's real wake/drain or
completion-work interleavings.

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
The runner owns the streamed child stdout pipe and must close it after the child
is reaped so repeated qualification stages cannot leak descriptors or emit
resource-lifetime warnings.
Retained synthetic write/flush fault PASS markers remain visible as phase
completion even though their marker prefix is not `PASS_LOADED_`.

Every top-level privileged helper invoked by `test-loaded.sh` also has a
root-owned outer watchdog in addition to its internal operation/replay
timeouts. Preflight is capped at 60s, the loaded smoke helper at 600s, the
primary lifecycle qualifier at 14,400s, each owned-RAM benchmark pair at 720s,
and the ID36 resource-pressure helper at 960s. Rootless source contracts that audit the loaded wrapper must pin this
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
domain-separated SHA-256 of `b"swapz-host-v2\0"` (the prefix with
its terminating NUL), the canonical lowercase 36-byte DMI product UUID and
lowercase 32-byte machine ID in that order. UUID hyphens are required at
positions 8, 13, 18 and 23; each identifier must contain a nonzero hex digit.
The two root-owned, single-link, non-group/world-writable regular files are
read without following symlinks, with stable metadata. Each allows exactly
zero or one trailing LF, never whitespace trimming or any other trailing bytes.
Missing, malformed, oversized or changing inputs, or an unavailable runtime
architecture, yield `UNAVAILABLE` with redacted `phase=host_identity` refusal
categories. The JSON schema label stays
`swapz-host-v1` because the production parser requires it; that label is not
the digest version. Raw machine IDs, DMI UUIDs and hostnames are never published. Only committed reports with
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

The independent source-contract job runs `io-replay-test.py` on a clean
checkout before any native suite has built its binaries. The rootless replay
suite must compile its exact `tests/suites/Makefile` leaf targets for
`io-replay-native` and `anon-page-analyzer` before executing their assertions;
a missing compiler, failed build or nonexecutable output is a failure, never
an oracle skip. Keep compilation unprivileged and separate from the release
qualification interface: `make fast_test` is still development-only, and
`make test` and `make test_full` are the two source-bound qualification
tiers, with physical acceptance still a distinct gate. Rootless failures
must name the phase, scenario, candidate, mismatched invariant or child exit
status, and a bounded reason without publishing representative samples or
private paths. Negative `MIXED_OPS=65536` CLI probes must still assert
`SystemExit(2)` and the exact ordinary-mixed-only restriction, while capturing
their expected usage stderr locally so the retained source-contract summary
points to the real failed replay invariant instead. Native leaf compilation
must have an internal timeout below the parent source-contract watchdog and
must retain only bounded, repository-root-sanitized build stderr on failure so
the first error still identifies both the build phase and its cause.

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

The historical `tests/tools/live-swap-supervisor.py` mutating CLI remains
permanently disabled for the retired host; its rootless worker fixtures are
not permission to run or recover real swap. Its real Linux adapter must also
have no raw block-zero write bridge: even a future accidental execution-flag
change must fail before any header clear/restore operation. Synthetic legacy
state-machine fixtures may model historical stages only in memory. A synthetic pressure PASS must
bind the validated qualified source, HEAD and one lowercase run ID through
the parent state and exactly one duplicate-free child JSON report. Require
the frozen page count and corresponding 4KiB byte count, zero mismatches,
confirmed anonymous-mapping close, zero cgroup OOM and OOM-kill events, positive independent
mapper usage and swap peak, and proof that the direct child was reaped and
its newly owned cgroup was removed. The 128MiB child memory cap, 80,000
pages and existing time limits are upper bounds, never knobs to raise for
a passing fixture. Missing, malformed, nonfinite, duplicate or exhausted
memory/PSI/cgroup evidence refuses admission. Intentionally generated PSI
still cannot silently defeat the conservative stop thresholds.

The rootless pressure-evidence regression must distinguish three failures.
A mismatched parent source/run identity is rejected before cgroup creation or
workload invocation, with `phase=pressure_admission`,
`original=identity_mismatch`, `errno=None`, `admission=source/run`,
exact expected pages/bytes, `UNVERIFIED` observations and retained
`LIVE_SWAP_ACTIVE` stage; it creates no workload phase. Exercise that
pre-admission refusal from pristine state and result evidence so a prior
`pressure_cgroup` or phase cannot confuse attribution. Separately retain an
otherwise valid `PASS`/`BYTE_EXACT` pressure phase, change only the top-level
run ID, and require `_actual_swap_io` to reject it because the child report
remains bound to the previous run. A same-run child reporting three corrupt
pages instead fails `phase=pressure_verify` with
`oracle=verified_page_count_mismatch`, exact observed pages/bytes and original
nonzero child exit, and must not be mislabeled as a run-identity failure. A
foreign-run child fails
`oracle=run_identity_mismatch` even when its counts equal expectations
and it exits zero. Post-workload failures retain `status=FAIL`,
`oracle_outcome=UNVERIFIED`, original exit and retained stage rather than
qualifying PASS. Error detail remains bounded and excludes page contents,
private paths and untrusted child text.

Rootless debugging must also prove that a malformed reaped-child wait status
cannot bypass parent pipe closure or an attempted owned-cgroup removal.
A failed durable write of the *initial* activation failure report must not
replace the first worker/integrity failure or skip the single normal cleanup
attempt; any such evidence-write error revokes PASS, including when the
initial stop was otherwise classified as SAFE_STOP. A failed final report
write likewise cannot return PASS, even when original swap restoration
was independently confirmed. Surface original failure category and secondary
write errno without printing private paths. Lower-device write evidence
requires positive independently observed **bytes and requests** for the
same bounded trial, never just one positive counter; missing or inconsistent
telemetry blocks qualification rather than being treated as a synthetic win.

Pressure cancellation may signal only the supervisor's unreaped direct child,
not every PID found in the pressure cgroup. Child waits and postreap report
reads remain bounded; an inherited report writer or unproven child death
retains recovery obligations.
The fork handoff must never lose that direct-child ownership: a parent pipe-close
failure after fork reaps the child before propagating, a child-side descriptor
failure exits the child rather than returning into the supervisor stack, and a
fork failure preserves its original errno while reporting descriptor-cleanup
uncertainty. OS-error diagnostics use the stable `OSError` category rather than
errno-selected Python subclasses such as `BlockingIOError`. Successful mutation phases retain no command stdout/stderr. Public phase argv redacts non-device absolute paths, and failed/interrupted phase diagnostics are bounded and path-redacted before they can enter printed result JSON. A surviving same-name cgroup from an interrupted run is retained
because its inode identity was never durably bound; recovery must not remove it
merely because it is currently empty. A failed write of the recovery-required evidence record is also a secondary
failure: append its errno, retain the original worker/mapper failure, and do
not claim teardown or durable recovery success. A first byte mismatch, worker signal/exit or
guard stop must survive a simultaneous pipe, memory-counter, cgroup-removal,
mapping-close or later mapper-cleanup failure. Errors identify the original
phase/errno or exit, memory/PSI category, expected/observed page and byte
verification counts, and whether the child, cgroup or mapper recovery state is
retained, without dumping page bytes or private paths. When failure occurs before
an oracle report exists, print the frozen expected page/byte counts and the
observed values as `UNVERIFIED` rather than omitting the comparison. The trial cannot
publish PASS on missing/reordered observation indices or regressing kernel
and lower-device counters.
Child reports with unknown JSON keys, additional records or nonfinite timing
must be rejected without persisting their untrusted payloads, which may
contain page contents or private filesystem paths. Do not persist the private state-directory path in the accepted result object. The accepted report schema uses typed
nonnegative counts and an errno-only mapping-close field. Before any synthetic
trial PASS, revalidate the bound run/source/HEAD/helper/artifact and historical
target/capacity identity, including the inspected physical-parent major:minor,
the frozen 128MiB/80,000-page resource limits, exact page and byte oracle result,
zero OOM/OOM-kill counters, positive mapper/swap use, proven child/cgroup
teardown, and availability plus monotonic ordering of every lower-I/O
observation. Lower-device accounting must pass that bound parent identity to
the shared block-stat snapshot helper and reuse the shared lower-delta validator,
including its exact 17-field Linux ABI, uint64 bounds, reset/wrap rejection and
512-byte sector conversion. Reject a substituted, truncated or unavailable
parent snapshot; partition counters are not a substitute for lower-media evidence. Rootless physical-parent admission fixtures use synthetic header bytes and must bind the expected header digest to those exact bytes before exercising parent-identity refusals; a historical real-header digest must not prevent the intended synthetic gate from executing. Rootless adversarial tests must inject both
termination uncertainty and failed teardown independently of a clean worker,
including a timeout followed by cgroup-removal failure. No synthetic PASS
proves actual anonymous-page reclaim, Linux swap-out/swap-in, maximum-capacity
behavior or the current dedicated-card deployment; those remain independent
loaded/current-host qualification gates.

The primary manager's direct production-C tests must exercise multiple synthetic
target identities and geometries, Device Mapper output variants, active-swap
parsing, header recognition, and fail-closed ownership decisions without
opening or modifying a block device. Include different major:minor values,
minor zero, different PARTUUIDs, and capacity/alignment boundaries so tests do
not encode the active owner's current partition as a production assumption.
The direct-C fixture must compile the plan in a mode that refuses all host
block-device and `/proc/swaps` reads; test the identity and signature parsers
with synthetic major:minor values and bytes. Host admission must require an
already formatted ordinary Linux swap partition, parse its valid
`SWAPSPACE2` geometry, hash the exact 4096-byte block-zero image and compare
that image with the transaction's manifest-bound digest before any mutating
transition. No provisioning step may manufacture or repair a raw swap header.

The plan must treat mutable lifecycle ownership as same-boot state under
root-owned `/run/swapz`. If that directory exists, require mode 0700,
root ownership, no symlink substitution and a tmpfs backing filesystem. On
first use, the read-only plan may accept an absent `/run/swapz` only after
proving the fixed `/run` parent is root-owned, not group/world writable and
tmpfs; the plan must not create the directory. A mutating owner may then create
only that fixed 0700 runtime directory. Because tmpfs has no physical backing
parent, runtime state must never require or report a separate recovery disk as
an admission condition.

Persistent signed qualification evidence may remain under
`/var/lib/swapz/physical-recovery`, but that directory is evidence storage,
not lifecycle ownership, swap metadata, a header backup or a recovery image.
It may reside on the same physical disk as the selected swap partition without
weakening swapz isolation because it is never consulted to reconstruct mappings
or restore the raw partition. Existing legacy `recovery_*` plan field names
are compatibility output only and must not regain physical-parent authority.
Internal helpers and PREPARE failure phases must use `runtime-state`
terminology; do not describe the tmpfs ownership store as recovery storage,
a persistent recovery filesystem, or a recovery-device admission dependency.

The selected target and root-source gates must still resolve device identity
through `/sys/dev/block`, match recorded major:minor values, reject unsafe
holders/stacking and prove that the root filesystem does not depend on the
selected swap partition. When the source being checked is the root mount,
mountinfo's superblock major:minor is not a substitute for the root directory's
`st_dev`: Btrfs subvolumes may report different virtual device numbers. The
private owned-RAM null_blk rehearsal may keep its isolated Btrfs source-chain
fixture, but that test-only relaxation cannot enable production or physical
Btrfs admission. Its block-backed private runtime directory may exercise
source-chain identity as a test fixture, but tests must not require a
target/recovery-parent separation phase or compare the swap target against a
fictional production recovery-device parent; production runtime ownership is
tmpfs-only. Any missing, changing or multidevice identity remains BLOCKED.
Rootless tests must use synthetic sysfs trees and cover malformed device
numbers, target identity, missing physical identity and nonempty holder or
slave directories without reading host block devices. Parse mountinfo strictly,
identify the unique `/` mount, verify its physical source chain excludes the
selected swap partition, and reject any mount whose major:minor is that
partition. Rootless mountinfo
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
systemd directives and generated dependencies, not descriptive unit comments.
The mapper unit may require the persistent qualification-evidence location
before its preflight/prepare chain because the signed report is read there;
that mount is not mutable lifecycle ownership or a swap-recovery dependency.
Systemd `RuntimeDirectory=swapz` supplies the volatile `/run/swapz` ownership
directory. The package-owned
file set and SHA-256 manifest must include the cold-boot verifier executable
(mode 0755) and verifier service (mode 0644); uninstall must reject modified
copies and remove only exact owned copies. Installation must substitute the
installed sbin path into both lifecycle services without enabling or starting
either one. The isolated systemd verifier fixture must run from the official
rootless contract stage, covering arm/preflight/observe success and fail-closed
raw-alias, identity, artifact, geometry, service and kernel-log cases without
reading or changing host swap state. The cross-boot preflight authorization is
one-use volatile authority: every observation, including PASS, FAIL, INCOMPLETE
and an unexpected persistence abort, must revoke it without touching active
swap or same-boot lifecycle ownership. Unlink and runtime-directory sync must
complete before PASS is persisted or announced. A revocation failure must
produce a non-PASS, nonzero result with the failed token-lifecycle phase and
original command exit status, retain earlier observation evidence, and never
print token contents or the runtime authorization pathname. Rootless cases
must cover missing, stale, duplicate and malformed authority, revocation
failure, preserved evidence, explicit re-preflight retry and abort cleanup.
Only completed unlink plus runtime-directory sync may suppress the EXIT
fallback; a failed revocation attempt must leave that fallback armed for a
later persistence abort or final process exit. The primary mapper service and package
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
output must fail without emitting a drop-in. The isolated generator transaction
test must not infer raw-swap safety by scanning unrelated generator output:
systemd unit generators execute concurrently, so an unrelated by-PARTUUID
`.swap` file or wants link may be present without gating the selected mapper.
Exact selected-unit collisions still fail closed, while same-partition raw-swap
alias exclusion remains an identity-based boot/deployment admission check.
Inject initial early-mask rename errors both before and after replacement,
and a false-success no-op: all must refuse the invocation with a verified
`/dev/null` mask, no target drop-ins, no temporary mask, and the original
command status. After selection changes, replace the prior mapper and device
drop-ins separately with foreign regular-file contents and retry failed
regeneration: the files must remain unchanged, with the early mask active and
explicit ownership-failure diagnostics.
Also replace each previously validated stale drop-in inode between comparison
and retirement: the foreign regular file must be restored or retained, the
`/dev/null` mask must remain verified, and diagnostics must name the inode
replacement and surviving artifact. Also inject a stale-device rename
which reports success after hardlinking the validated inode into staging
without consuming the original name, and a successful rename followed by a
foreign symlink at that original name. Both must fail under `/dev/null`,
retain unowned source data, remove temporary owned staging, and never publish
the new selector graph. Pause one invocation after it publishes
its graph but before final mask release, start a second invocation that later
fails, and prove the second cannot clean the first graph until the first has
released transaction ownership; after the second fails, the early mask must
remain and no partial graph may be active. Inject generator-transaction lock
failure and temporary-mask cleanup failure as well, preserving the exact
original/restore command statuses rather than collapsing them to boolean
failure. Repeat a narrowly injected initial-mask rename failure that
substitutes a foreign symlink, falsely succeeds at unlink, and falsely
succeeds at direct replacement. The result must give the initial rename and
secondary restore rename distinct injected statuses, preserve the final
restore-verification status separately, classify foreign versus owned state,
report the observed early mask, incomplete rollback and required operator
action, and publish no selected-target drop-ins.
Inject final early-mask unlink failure both before and after the unlink,
false-success unlink, mask-restore rename failure before and after the rename,
and a foreign mapper-unit symlink substituted after mask removal. A refused
generator run must replace that substitution with the early `/dev/null` mask,
remove both pinned mapper/device drop-ins, preserve the first failing command
status, report restore status separately from unavailable syscall errno, and
report the verified rollback outcome without disclosing selector contents.
A final mask unlink that returns zero does not prove that publication committed:
recheck both public mapper/device drop-ins against their pinned staging inodes
immediately before and after mask release, refuse a substituted symlink or
regular inode, restore the early /dev/null mask, and preserve the foreign
artifact. In a rootless transaction negative control, inject each kind of
mapper-drop-in substitution within a zero-status mask-release wrapper; the
old generator must falsely commit, while the corrected generator must
report publication ownership failure, rollback incompleteness and the
verified retained mask. Treat the no-follow mask replacement and EXIT-trap
postconditions as independent checks after a first genuine command failure:
zero-status cleanup is never enough to establish absence of stale paths.
A failing generator must reverify the early `/dev/null` mapper mask after the
EXIT trap has finished all cleanup mutations, not only before cleanup starts.
Once rollback begins, HUP/INT/TERM must be ignored until cleanup has reverified
its owned publication state and early mask. Inject TERM from a cleanup command
after a genuine publication failure and require the original failure status,
verified mask, no owned target drop-ins or private staging, and complete rollback.
Inject secondary cleanup commands that return nonzero after unlink or report
success without unlinking, then substitute a foreign early mapper-unit symlink.
An independently staged mask replacement must recover even when the direct
no-follow link command falsely reports success. Preserve foreign targets and
unconsumed owned inodes, retain the verified mask, and report original command
status, secondary cleanup and mask-repair statuses, observed staging survivors,
and rollback completeness without logging selector bytes. Include a failure
before any selected-target drop-in has been published. Explicit post-release
rollback must carry the original unlink or ownership failure status into its
cleanup observer instead of treating a successful mask-restoration command as
the original status; foreign inode survivors still require full diagnostics.
When both direct link replacement reports false success and staged mask rename
fails, cleanup must try a final verified unlink/direct-link at the reserved
early mapper-unit name. A false-success or failing unlink must be classified
using source-path absence, and the rename error status must remain visible
separately from the original generator failure and the final mask state.

The standalone `tests/runtime/native/systemd/swapz-primary-generator-transaction-test.py` transaction fixture is
mandatory in the rootless `make test` stage: `tests/tools/test-rootless.sh`
invokes it exactly once, enforced by `tests/runtime/native/source-contract-test.py`.
The existing Systemd/package workflow also runs it indirectly through its
workflow-contract fixture; it must not add a duplicate direct invocation.
The rootless stderr classifier also recognizes `GeneratorPublicationTest` so a
failed adversarial assertion names its responsible test method without exposing
private generator stderr in the public failure marker.
Generator subtest context with arbitrary keys remains private; its allowlisted
method is still identified, while only a validated `phase=` tag can appear as
a public subtest value. The rootless attribution regression must execute the
actual registered generator stage with a synthetic non-`phase=` subtest,
retain the method and failure kind in the public marker, and keep that subtest's
value confined to the private diagnostic.
The primary lifecycle audit must use the same bounded, fail-only private
stderr capture as the primary real-swap unittest stages. Its four registered
classes (`PrimaryLifecycleBehaviorTest`, `PrimaryLifecycleSourceGuardTest`,
`PackageCrashToPrimaryAdmissionTest`, and
`PrimaryOwnerReleaseDurabilityTest`) form a phase-specific allowlist:
only a matching first verbose failure and detailed FAIL/ERROR block may
supply a public test name, failure kind, or genuine exception errno. The class
captured by that first verbose progress record is part of the authenticated
identity and must match the detailed block exactly; membership in the same
suite allowlist is insufficient. Bounded oversized-log retention must use that
same class, method, failure kind and validated phase context so a wrong-class
block cannot donate errno or displace the first-cause excerpt. Expected
negative output from another class and later cleanup exceptions must never
replace the first cause or exit code. Subtest values and exception payloads
remain in the mode-0600 private log, never the public marker. The rootless
attribution fixture must exercise this actual registered lifecycle stage with
passing streams, a foreign-only failure, and reordered cleanup failures.
Its raw-string Bash fixtures must emit real newline-delimited unittest records
and use single shell-continuation backslashes; doubled escapes would test a
malformed transcript rather than the first-failure contract.

The suite needs Python 3, Bash and GNU userspace commands, and operates only on
private temporary directories with a stubbed manager. Generator subprocesses
have a 30-second bound, and the official rootless stage keeps the original
nonzero test exit, privately captured stderr, and suite-phase attribution.
No service start, installation, swap activation, or device access is permitted.
On every generator refusal, retain the original numeric command or validation
exit status and emit only an allowlisted identity class: `not-evaluated`
before selector evaluation, protected/unverified PARTUUID once manager
selection begins, or manager-validated PARTUUID after canonical response
validation. The expected mapper-to-device/raw-swap conflict graph remains
redacted; its observed state is `not-evaluated` before selection and
`unverified` until successful publication. Remediation must stay read-only
and match the phase: invocation/output-directory inspection before selection,
mask and selector inspection while selection is unresolved, then generated-unit
inventory inspection as well after canonical response validation. Rootless
tests must exercise all three identity-class states with controlled
failure exits. Never reveal the private PARTUUID, selector text, or host device
path, and never log this failure envelope on successful publication.
The final failure envelope must include the fixed mapper unit, the expected
native start/stop owner, actual verified/unverified early mask state, and
original command status. The pre-directory argument refusal must remain
canonical even if the environment supplies the generator's internal mask-state
gate as `1` or as nonnumeric text: exit 2, report `observed_mask=not-evaluated`,
and do not inspect an unset early directory. The transaction fixture must run
rootless `systemd-analyze verify` against its existing fake early/normal
generator directories and a normal-priority passive swap shadow. With systemd
debug unit output enabled, a valid graph must show the generated mapper drop-in
and its exact selected `Requires`/`After` device plus `Conflicts`/`Before` raw
swap relationships; after an invalid selector, the mapper must be masked and
those effective target-specific relationship lines must be absent. This proves
configuration precedence, not real occupied-swap shutdown behavior.

These dependencies are not a
complete activation policy: a raw swap entry may be named by UUID or another
alias, so deployment must separately ensure the selected partition is not
activated through that alias. Current units remain disabled and
`RefuseManualStart`/`Stop` stays in force until the full lifecycle and boot
path are qualified. The manager must use the same
permanent selected-PARTUUID lock for all of its operations; tests must reject
an unsafe lock directory, lock file or concurrent owner before any mutation.
The passive mapper .swap unit must keep an always-false
`ConditionPathExists=!/` under `[Unit]`: `RefuseManualStart=yes`
blocks explicit starts only, not dependency-pulled jobs from an accidental
`swap.target.wants` link or fstab entry. The mapper service remains the sole
swapon/swapoff owner, while the .swap unit observes `/proc/swaps` without a
systemd start job. The exact-SHA systemd/package rootless contract must run
`systemd-analyze verify` on the escaped swap unit name and
`systemd-analyze condition` to prove that an indirect start is skipped.
Because normal generator output outranks packaged `/usr` units, the vendor
condition alone is insufficient: `swapz-primary-generator` must mirror
`RefuseManualStart=yes`, `RefuseManualStop=yes`, and the same false condition
in a name-specific `generator.early` drop-in before it releases the
mapper-service mask. It must recheck that guard both immediately before and
immediately after mask release; a missing, replaced or noncanonical guard
keeps or restores the mapper mask, and a foreign noncanonical guard must be
preserved rather than overwritten. Canonical passive-guard verification must
be byte-exact without reusing the manager-response `cmp` fault path, so an
injected comparison failure keeps its original selection phase and status. If
the early generator directory becomes inaccessible after mask release, report
publication ownership as unprovable rather than misclassifying it as guard
loss. The rootless package contract must model a normal-dir fstab-generated
mapper swap that shadows the vendor unit, prove the
unguarded effective unit has no blocking condition, then prove the real
generator's early drop-in restores the passive lifecycle refusals and makes
the same indirect job fail its condition. No service start or real swap action
is permitted. A same-boot active-ownership marker is required before the
provisioning path can be enabled.

The native lock primitive must open the same
`partition-<selected-partuuid>.lock` inode under `/run/swapz`, reject
symlinks and unsafe ownership or modes, acquire a nonblocking exclusive
`flock`, and fsync the runtime-state directory. It must not unlink or replace
that inode during the boot. Until lifecycle commands actually acquire and hold
this lock for their full operation, the primitive's presence alone does not
satisfy the manager's shared-lock requirement. Reboot intentionally removes
the tmpfs lock and all other mapping authority; no cross-boot recovery lock is
required. Direct-C run-ID policy coverage must reject the all-zero ownership ID
and accept nonzero 32-hex IDs with leading or trailing zero digits,
consistently with the OS-random generator.

Before the first device mutation, consume a fresh lowercase 32-hex run ID with
an `O_EXCL` record and create the matching active PARTUUID marker under
`/run/swapz`. Each record must be root-owned mode 0600, fsynced, and followed
by a runtime-directory fsync. A partial or uncertain claim stays consumed for
the current boot and blocks another owner until checked same-boot reconciliation.
Only verified teardown after a COMPLETE lifecycle state may release the active
marker; reboot discards these volatile records and cannot recover swapz
mappings.

Mutable lifecycle state must use a root-owned 0600 temporary file, bounded
record size, file fsync, identity-checked atomic rename and runtime-directory
fsync. Reject symlink or non-regular replacement targets, and fail closed if
the ordering step is uncertain. Rootless direct-C tests must update an existing
record and preserve it when a symlink target is presented. The same-boot state
is `/run/swapz/primary-state.json`; it is deliberately not stable across
reboot. Package removal or upgrade must refuse while this state file or an
active ownership marker exists, including dangling symlinks at either path,
so package mutation cannot race a live owner. Persistent
`primary-qualification.json` evidence under `/var/lib/swapz/physical-recovery`
is separate and does not become runtime ownership. The rootless package test
must cover these refusal cases.

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

Same-boot lifecycle reconciliation/teardown must refuse while any `swapoff`
process runs in a swapoff stage, even when the kernel still lists the device,
and an unreadable `/proc` entry fails closed. Rootless suites for this procedure run with privileged commands refused
(for example through a `sudo` stub that exits nonzero). The physical-swap-probe
suite simulates its physical run with mocks, so it must pass under that stub
and must never be run unguarded on the PC.
The recovery-order tests must mock live target identity and Device Mapper
inventory without touching a host block path, but must retain actual header
read-before-swapon and no-raw-write assertions. The development simulator must
bind its private exact run directory to the current runtime-state and algorithm
base helpers, not the removed persistent `_recovery_base` API. Missing-activity
and pending-recovery controls must still assert no premature runtime or legacy
state access. Preserve the executable bit of the physical-swap test script.
The synthetic recovery fixture must persist identical, strictly typed geometry
bindings (`swapz_logical_sectors`, `swapz_linux_swap_kib` and
`swapz_physical_blocks`) in saved state and results. Independent negative
controls must corrupt each results geometry value and prove refusal before
target inspection, mapper inspection, or block-zero writes; stale fixture
records are not evidence of an unsafe recovery implementation.

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
target mutation. `swapon` must follow the released-swap-cluster DISCARD activation policy above; activation-time whole-area DISCARD remains forbidden. Never remove an active swap
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
remains blocked. Ordinary production must not read that private marker. Its
same qualified artifact is instead runtime-locked by volatile
`/run/swapz/primary-execution.env`, created only by successful owner-armed
cross-boot preflight. That record must be root-owned mode 0600 under a
root-owned mode-0700 runtime directory and exactly bind current boot ID, build
source SHA, canonical configured PARTUUID, the selected partition's current
major:minor, and target byte size. The major:minor is deliberately boot-local:
it need not match the pre-reboot arm record, but any detach/re-enumeration that
changes the selected partition device number invalidates prepare/start until a
fresh owner-armed preflight mints a new token. Failed or
repeated preflight removes any earlier token before checking current facts.
A cold-boot observation that durably records FAIL or INCOMPLETE must likewise
remove the volatile token so the boot cannot authorize a later prepare/start;
that revocation must not prevent exact durable stop/recover cleanup. The
public Makefile and package must never define, install or expose either test
seam. The source contract must inspect the root
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
partition identity, qualified source and artifact hashes, expected mapper
identity and geometry, and the SHA-256 of the immutable ordinary SWAPSPACE2
block zero. Do not persist a 4096-byte block-zero backup: lifecycle and recovery
must re-read the exact selected target, validate its Linux swap header and
geometry, and compare the live block-zero digest with the manifest.

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
mismatch, unsafe runtime-state ownership, target identity/header drift, nonzero
selected-target swap use, duplicate or ambiguous selected-target swap aliases,
mount/root dependency, loaded module or existing mapper. Unrelated swap entries
may remain active and must never be modified by metadata preparation. It must
repeat the exact swap and block-zero checks immediately before claiming. After claim, focused rootless lifecycle tests must verify same-boot
consumed/`READY`/active ordering, manifest readback, interruption handling
after each ownership publication, and the atomic `READY` close and
owner-marker release. Runtime ownership is volatile RAM-backed state; it is not
a swap-partition recovery image and must not require another physical disk. Where platform behavior is
needed, use deterministic fault injection on an owned RAM-backed `null_blk`
target; no such test may open or write a host block device. The rootless build
must keep the command unavailable and prove no host path or lifecycle side
effect is reached. After the ordinary loaded owned-null_blk smoke, the official
loaded stage must also execute one private success-cycle rehearsal with
`SWAPZ_PRIMARY_OWNED_NULLBLK_TEST`: create a uniquely owned memory-backed
null_blk disk, create exactly one real partition with a kernel PARTUUID using
`sfdisk --lock`, and rely on sfdisk's normal kernel notification rather than
issuing a second unlocked `blockdev --rereadpt` that can race with udevd. The
fixture must convert the actual lower `/dev` node's `rdev` to major:minor and
require an exact match with the owned null_blk sysfs device number before
`sfdisk`. Settle udev before enumerating the partition, then require the actual
partition node's `rdev` to match the partition sysfs device number before
`blkid` or `mkswap`. Verify its PARTUUID against the partition's sysfs uevent,
trigger udev's add event only for that exact sysfs partition path, and require
udev to publish the by-PARTUUID block-device alias with that same partition
major:minor. Before any physical-backing mapper admission, the fixture must initialize its
owned synthetic partition once as ordinary Linux swap, validate its
`SWAPSPACE2` first page and hash that exact 4096-byte page. Mapper construction
must then accept that unchanged Linux swap header only through the normal
physical-backing opt-in and qualification gates. The mapper uses the data area
after the protected first page; the raw synthetic partition must not be
reformatted, cleared, or given a swapz-specific authorization header.
Some host persistent-
storage rule sets deliberately exclude `nullb*`; when the normal rules do not
publish the link, install one temporary udev rule matching only the verified
partition's exact `DEVPATH` rule key and PARTUUID, reload the rules, and trigger that
partition again. The temporary rule must import the partition-table UUID in
one rule and match it in a subsequent rule, because udev checks match keys
before applying assignments from the same rule. Prove the link in udev's
recorded `DEVLINKS` property as well as by block-device identity; never create
the alias with a shell symlink.
Remove the temporary rule after null_blk teardown and require its alias to be
gone. If publication fails, capture the exact fixture rule, relevant udev
properties, and udev's event-rule diagnostic before cleanup. The raw
rule, PARTUUID and DEVPATH remain in root-owned private failure evidence;
public diagnostics carry only phase, original errno when observable (or
`unavailable`), expected and observed identity classes, ownership status,
and the next read-only inspection action. A definitely failed setup operation
after fresh null_blk creation is FAIL, not preclaim BLOCKED. The rootless
partition-write failure fixture must initialize its synthetic disk ID before
expanding the real sfdisk here-document, so the injected command failure
reaches the owned-operation FAIL classifier rather than an unrelated shell
nounset/redirection failure. A definite owned setup command failure must
retain the immediate original shell exit status in a bounded
`original_exit=<number>` diagnostic; shell exits are not errno and
`original_errno=unavailable` must remain explicit unless a native errno was
actually observed. In particular, avoid `if ! command` around a failing
`sfdisk` when that inversion would discard its first exit. The rootless
partition-write fixture injects exit 11, proves that exact first status
survives the FAIL classifier, and verifies byte-for-byte unchanged foreign
and owned test sentinels without publishing fixture identities. Missing exact udev
publication after otherwise successful commands is not a proven owned-operation
failure: it remains BLOCKED. Preserve its raw diagnostic only in private
evidence, then allow normal identity-revalidated teardown of the positively
owned fixture; quarantine the device or rule only if that rollback becomes
unprovable or fails. The refusal can never be promoted to PASS. Initialize only
that RAM partition using the portable plain `mkswap <partition>` form; do not
pass `--no-discard`, which is not an `mkswap` option.
The primary-lifecycle fixture has a valid ordinary `SWAPSPACE2` header before
creating its mapper. `dm_swapz` must validate that unchanged header on the
owned null_blk partition, require `allow_physical_backing=1` plus the loaded
RAM-metadata qualification token, and reserve physical block zero. Only the
virtual mapper receives `mkswap`; invalid or unformatted physical-partition
headers fail closed, while the isolated whole-device null_blk test mode remains
a separate synthetic path. With the physical opt-in disabled, constructor
refusal must not change lower-device I/O counters.
The start/stop rehearsal therefore verifies exact Linux swap activation and
byte-exact preservation of the original backing `SWAPSPACE2` page. The
owned-null_blk harness independently hashes lower block zero before admission,
after successful start, and again after normal stop, and requires identity
before publishing lifecycle PASS.

Compile a noninstalled exact-source
`swapzctl` under a root-owned private prefix, and generate a private
parser-valid qualification record bound to the exact test binary/module/oracle
hashes, live host identity, and running kernel release. The production coordinator
must then complete
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
be imported into production qualification-evidence storage. If initial
lifecycle preparation refuses, capture the read-only `primary plan` output before cleanup even when
the command exits with its expected BLOCKED status, so the exact failed target,
recovery, mount, swap or artifact gate remains visible in the owner report.
A validated preclaim preparation refusal (including report-import and global
lock admission) remains BLOCKED; a validated postclaim operation failure with
canonical retained-owner evidence is FAIL. Cleanup cannot promote either to
PASS, and a failed post-removal UDEV settle retains private evidence with an
explicit phase-specific quarantine diagnostic. The
owned-null_blk build may
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
never infer swap inactivity from a skipped entry. The rootless qualifier contract
must run `bash -n` and pin each normal-start ACTIVE proof step exactly once and
in execution order, including adjacency between the unique active-swap count
predicate and its fail handler. Mere substring presence is insufficient because
a syntactically valid misbound `||` can otherwise make a later assertion its
failure branch. The unprivileged loaded-test parent must establish the clean
checkout at the exact validated HEAD before
sudo, pass that SHA explicitly to the lifecycle helper, and recheck Git metadata
after the child returns. The privileged lifecycle helper must not invoke Git; it
must instead bind the passed SHA to the generated clean build-info provenance
before using exact-source module/oracle artifacts.

The same private rehearsal must exercise negative kernel-boundary cases against
the real coordinator: ambiguous `swapon` and `swapoff` outcomes both with and
without the kernel operation applied, unreadable post-operation swap inventory,
a definite failed `swapoff`, a wrong inactive mapper identity, stale run ID,
a failed durable state-directory `fsync`, and lost state provenance. The
state-directory fault must select the second *directory* `fsync` in the fresh
start process: the first follows partition-lock creation, while the second is
the durability barrier after the STARTING state temp file is fsynced and
atomically renamed. Regular-file `fsync` calls must not advance that ordinal,
so harmless file-sync changes cannot silently retarget the fault. A test-only
linker-wrap fixture may intercept only the private owned-null_blk binary's
`syscall`, `/proc/swaps` `open`, and `fsync` boundaries and must forward
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
The loaded-stage wrapper must bound the complete success, all 18 native-process
interruptions and the negative rehearsal without weakening per-operation
timeouts or quarantine-on-uncertain-cleanup policy. The 18 interruption points
are eight start-path milestones, five stop-path milestones, and five recovery-
path milestones, matching the production hooks and official report parser.
Owned-null_blk qualification must kill a fresh recovery process immediately
after durable RECOVERING, swapoff, mapper removal, module unload and durable
RESTORED. Each recovery interruption must preserve the first
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
`swapoff` is ordered before mapper removal in both stop and recovery. The privileged execution capability remains runtime-disabled by default until
the owner-armed cross-boot preflight authorizes the exact current source and
target; source presence of the syscalls alone is not authorization. A metadata-preparation PASS is not start, live-swap,
loaded-recovery, boot, performance, or production qualification.

The prepared-start coordinator may consume only an exact owned `READY`
transaction whose current configured target, immutable manifest, accepted owner
qualification and live artifact hashes still match. Before persisting
`STARTING`, it must revalidate mount/root/recovery topology, prove the selected
partition is not active swap, verify module/mapper absence, open the
manifest-bound PARTUUID target exclusively, validate the ordinary
`SWAPSPACE2` header and exact geometry, and require the live 4096-byte
block-zero SHA-256 to match the manifest. Block zero remains immutable. Only
after `STARTING` is durable may it record module-load intent, repeat the
last-use topology/selector/target checks, reverify the same block-zero digest,
load the exact qualified module, create/resume the exact run-bound mapper,
initialize Linux swap metadata on that mapper, call native `swapon` through
`/proc/self/fd/N` for the already verified mapper descriptor, and prove that
`/proc/swaps` contains the exact mapper device while the raw backing device is
absent before persisting `ACTIVE`. A successful syscall return alone is not
activation proof. The primary manager is the sole owner of swap activation; the
packaged `.swap` unit is a passive status view and must not be independently
enabled or used as a second lifecycle owner. Every failure after durable
`STARTING` must mark `RECOVERY_REQUIRED` while the owner lock is still held.
Normal stop persists `STOPPING` before deactivation and cleanup, calls native
`swapoff` for the exact verified mapper when active, and proves it absent from
`/proc/swaps` before mapper removal. It must remove only the exact
manifest-bound mapper with zero swap/open references, unload only a module
backed by the same run's exact `LOADED` ownership record and matching source
provenance, then exclusively reopen the manifest-bound backing target and
repeat the ordinary-SWAPSPACE2-plus-digest check before persisting `RESTORED`,
terminal `COMPLETE`, and releasing the active owner marker. Normal stop and
recovery never format, replace, zero, restore or otherwise write block zero.
Any failure after `STOPPING` but before `COMPLETE` must mark
`RECOVERY_REQUIRED`.

Every Device Mapper lookup of an existing mapper must submit its exact
run-bound UUID as the sole selector, then validate both the returned UUID and
mapper name. Linux rejects an ioctl that supplies both name and UUID for a
lookup. `DM_DEV_CREATE` is different: it creates the mapper and must bind both
the expected name and UUID. Production-C tests must preserve this distinction.
The target preflight input PARTUUID may alias the output target's `partuuid`
field; normalize and snapshot it before clearing or replacing the output.

Standalone recovery accepts an exact owned `RECOVERY_REQUIRED` record or a
durable stage that may remain after an abrupt process exit once mutation could
have begun: `STARTING`, `ACTIVE`, `STOPPING`, `RECOVERING`, or
`RESTORED`. It must reject `READY`, `DISABLING`, and terminal `COMPLETE`.
For a recoverable non-`RECOVERY_REQUIRED` stage it first validates the exact
manifest and the live immutable backing header, then durably normalizes the
state to `RECOVERY_REQUIRED` while preserving the original interrupted stage
before entering `RECOVERING`. This covers process death before the failing
coordinator could mark recovery itself, including stale `ACTIVE` after a
reboot; a live swap mapper still cannot be removed because the mapper-removal
gate refuses active swap and open references. Recovery retains the original
interrupted-stage provenance through `RECOVERING`, `RESTORED`, and
`COMPLETE`. Before cleanup it must revalidate the configured PARTUUID target,
read block zero, require a valid ordinary `SWAPSPACE2` header with exact
partition geometry, and require its SHA-256 to match the manifest. Any malformed
or changed block-zero bytes stop recovery before cleanup. It then persists
`RECOVERING`, removes or proves absent only the manifest-bound inactive mapper,
and unloads a module only when live provenance matches the manifest and the
per-run module-load WAL is `LOADED` or, for the crash window around
`finit_module`, `INTENT`. A failure before INTENT may have no module-load
record; recovery may proceed only when the module is actually absent. After
cleanup it exclusively reopens the same manifest-bound target and repeats the
same SWAPSPACE2-plus-digest verification before persisting
`RESTORED`/terminal `COMPLETE` and releasing the owner marker. Recovery never
writes or restores block zero, never force-removes a mapper/module, and never
adopts a live module without matching WAL. Any failure after entering
`RECOVERING` must return to `RECOVERY_REQUIRED` while preserving the original
interrupted stage. Keep execution disabled until the required
interruption/null_blk/physical evidence are complete.

The primary manager must persist only the block-zero SHA-256 in the immutable
run manifest, never a 4096-byte header copy. Rootless direct-C coverage must
construct a valid ordinary Linux swap header and prove exact digest acceptance,
valid-header byte changes returning `ESTALE`, malformed signature/geometry
returning a fail-closed error, and manifest tampering rejection. Start, stop and
recovery must read block zero only through the freshly revalidated
manifest-bound target descriptor. `mkswap` is permitted only on the newly
created swapz mapper; no lifecycle path may format, replace, zero, restore or
otherwise write block zero of the backing partition.

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
The root Make-interface fixture must distinguish a clean-to-dirty provenance
transition from ordinary dependency incrementality: the first production
source edit changes the embedded clean bit and must rebuild both
`swapzctl` and `dm-swapz.ko`. Once the dirty provenance is stable, a further
userspace-only edit must rebuild `swapzctl` without rebuilding the module, while
a shared kernel/userspace header edit must rebuild both. The fake Kbuild output
must include the staged build-provenance header and the kernel header exercised
by that regression so these checks model the actual artifact dependencies.

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
The package suite must run the installer against a private snapshot of its
package inputs with canonical safe file modes and a module destination tree
created with exact safe directory modes, independent of the test process
umask. This keeps the suite hermetic without weakening production admission:
the installer must continue rejecting group/world-writable inputs and
destinations.

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
The rootless build-header regression must exercise the current package
admission predicate: a source SHA mismatch or `SWAPZ_BUILD_SOURCE_CLEAN != 1`
must reject, while an exact lowercase source SHA with a clean bit of `1` may
pass. Keep malformed or uppercase source identities in the rejection cases;
the test must follow the implemented conditional's semantics instead of
depending on an obsolete source-text spelling.
The trailer sanity check must match the kernel's `mod_check_sig()` contract:
PKCS#7 id type, zero algorithm/hash/signer/key-id/reserved-pad parameter bytes,
and a positive signature length strictly smaller than all bytes preceding the
12-byte trailer; the kernel's equality boundary must reject. A cryptographically valid CMS payload
with any kernel-rejected nonzero parameter byte is malformed and must not
qualify. The real-CMS rootless regression must mutate every such trailer field
independently and prove refusal; marker text alone is never signature proof.
Embedded CMS signer certificates must be excluded from signer resolution
(OpenSSL `-nointern`): `-certfile` alone does not force verification against
that exact configured and enrolled certificate.
OpenSSL CMS verification can also accept an attached CMS whose embedded
content matches the supplied payload, and it accepts detached SignedData with
an eContentType that Linux rejects for module signatures. Before declaring
signature validity, require absent encapsulated eContent and the pkcs7-data
eContentType OID 1.2.840.113549.1.7.1. Keep this structural check on already
required tooling so it does not change earlier missing-tool/enrollment
failure precedence. A real-CMS rootless control must prove a valid detached
pkcs7-data signature passes while same-payload attached and wrong-content-type
signatures refuse.
The hermetic package-signing mock must model `openssl cms -cmsout -print`
separately from `openssl cms -verify`: a well-formed detached pkcs7-data
structure reaches cryptographic verification, where an invalid signature
retains its original verifier status and `phase=detached_signature`; attached
or wrong-content-type structure fails earlier with `phase=cms_verification`.
Do not let an empty mock description accidentally turn valid CMS structure
into a structural-parser failure.
Certificate identity, `mokutil --ignore-keyring --test-key` firmware-MOK
enrollment, embedded signer/key metadata, cryptographic signature validity,
kernel-keyring visibility, and target-kernel acceptance are separate facts.
The signing-hook regression must bind enrollment to the exact certificate
response rather than to a status code alone. Upstream mokutil 0.7.2 returns
status 1 for the exact certificate-bound `<path> is already enrolled`
response and status 0 for `not enrolled`; newer upstream reverses those two
statuses. Accept only status 0 or 1 paired with the exact positive
certificate-bound response, reject either status paired with `not enrolled`,
and reject every other status/output combination. Cover positive enrollment
under both conventions, absence, wrong certificate/path, malformed and
inaccessible certificate material, ambiguous or extra diagnostics, locale
normalization, missing `mokutil`, permission failures, and unexpected
statuses. No substring match, empty success output, or status value by itself
may qualify enrollment.
The signing-hook regression must treat both exact positive pairs as positive
controls: status 1 with the certificate-bound message for mokutil 0.7.2, and
status 0 with that same message for newer versions. In particular,
`status-zero-exact` is not a negative case. Warning text, wrong certificate
paths, empty output, and other status/output combinations remain negative.
The incremental root-Make fixture must use an inert, argument-checking signing
stub and record its calls; it must not invoke the host MOK, private key,
`mokutil`, `kmodsign`, or `sudo`. The separate signing-hook fixture exercises
the real helper with hermetic command mocks and a bounded test root.
The rootless signing regression must also model `sudo kmodsign` replacing the
module inode with a root-owned mode-0600 output. Signing mode must restore the
invoking build user's uid/gid before every unprivileged cryptographic
verification, including a pre-existing signed inode from an interrupted build
and the new inode produced by the current signer. Ownership restoration must
not widen the production file mode; the root Make target normalizes the final
0644 artifact only after the module recipe succeeds. `--verify` remains
ownership-read-only. Inject a failed signature-generation command while proving
the unsigned module bytes remain unchanged; if ownership cleanup also fails,
retain the signer command status as the primary failure and report the bounded
cleanup status separately. No private-key path/content may reach diagnostics.
Verifier temporary-directory cleanup is also checked: a cleanup-command failure
must refuse an otherwise successful signature check or unsigned pre-sign probe.
An earlier verification failure, including unsigned `--verify`, CMS parsing or
cryptographic verification, retains its original phase and producer status while
cleanup failure is reported independently. Rootless `rm` mocks must exercise
both precedence classes without leaking signing material or temporary paths.
Raw signing-command stdout/stderr must not be replayed on failure;
report only bounded phase/status context. Failure diagnostics must identify the true phase (including
`phase=certificate_enrollment`, `phase=detached_signature`,
`phase=module_vermagic`, or `phase=signature_generation` as applicable) and
retain the original producer/command status rather than broadly treating a
nonzero result as equivalent evidence.
`modinfo` signer or `sig_key` metadata is diagnostic only and must never
substitute for cryptographic verification. Packaging may report cryptographic
validity plus enrollment, but it must not claim that the target kernel
accepted the module under its configured enforcement policy until the same
exact installed bytes have been safely and authoritatively loaded by that
kernel.

The package qualification JSON parser must reject duplicate keys in every
object, including nested stage and qualified-artifact records, before any
package mutation. Its refusal names only the sanitized duplicate key and never
prints report contents or paths. The rootless package regression must use a
conflicting nested digest where permissive last-wins decoding would otherwise
admit the valid final value, prove the installed package and DKMS log remain
unchanged, and then prove that correcting only the report restores ordinary
upgrade admission.

Package and Secure Boot refusals must identify `phase=signature_generation`,
`phase=ownership_restore`, `phase=cms_verification`, or
`phase=installed_artifact_provenance` when the corresponding boundary fails.
Package and Secure Boot refusals must emit bounded, fail-only diagnostics
that name the artifact or status check, its expected versus observed digest or
provenance/status class, any known command exit status, retained-state
disposition, and the next read-only inspection. Never include absolute host
paths, private signing-key or certificate material, or machine-specific
identifiers. An installed qualification marker is a claim to inspect, **not**
independent proof that the bytes are qualified; mark its comparison provenance
unverified. Missing installed `swapzctl`, mismatched installed module bytes,
wrong module vermagic, stale/missing DKMS registration and Secure Boot
signature/enrollment failure must all remain BLOCKED. A verified detached
signature plus an enrolled MOK must never imply kernel load acceptance.
A hash producer that exits unsuccessfully must not establish artifact identity
even when its stdout matches the expected SHA-256. Every qualified-input,
staged-copy, retained-snapshot and installed-artifact digest refusal must name
the exact artifact class, expected versus observed digest/provenance, producer
status and safe read-only next step. Recovery snapshot path-key hashing must
capture and validate the hash producer result before using it as a backup
filename; nesting that producer inside another command's argument must never
hide its failure status. Rootless package fixtures must exercise plausible
digest stdout with failed producers for qualification inputs, staged/promoted
artifacts, existing installed files and snapshot path-key generation.
Secure Boot state admission requires a complete recognized state from a
successful `mokutil --sb-state` probe, or the existing direct EFI-variable
fallback when `mokutil` is absent. If `mokutil` fails and `/sys/firmware/efi`
is absent, that independent runtime fact identifies a non-EFI host, where the
module is not signed; if EFI runtime exists, the failed probe is indeterminate
and must BLOCK with its original status. A successful but contradictory or
unrecognized `mokutil` result also remains indeterminate and must BLOCK rather
than trusting plausible stdout. Recognized forms include the standard
single-line enabled/disabled results, disabled plus the Setup Mode annotation,
and enabled plus shim-validation-disabled; the last case still requires the
exact module signature verification because firmware Secure Boot is enabled.
A rootless `dkms status` mock must print the otherwise exact installed record
and then exit nonzero. Both install and uninstall must reject the producer
failure without authenticating stdout or modifying the installed package.
Nonzero `modinfo` exit status invalidates
module vermagic and installed module-path resolution even if stdout appears to
match; synthetic negative controls must prove both refusals before package
mutation. Installed-module lookup refusals must report a bounded path-status
class and producer status without printing the resolved path. Stale/ambiguous
all-kernel DKMS registrations and foreign module images must likewise name the
failed scope or module-image-set check and direct the operator to read-only
DKMS/module inspection.

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
fsync every snapshot file and its containing directories at the initial
`prepared` checkpoint, then atomically publish an independently verifiable
state manifest containing hashes of every recovery file. The prepared
checkpoint must also durably record the new transaction-directory entry before
any removal. The installer must not modify the snapshot after preparation:
every later phase must recheck its file hashes and metadata, fsync its new
journal file and the transaction directory, and need not re-fsync the unchanged
snapshot files, backup directories or transaction parent. Rollback journal JSON
is exact-schema authority: each backup-file record contains only `path`,
`sha256`, `size`, `mode`, `uid` and `gid`; numeric metadata must be JSON
integers, never booleans or floats. Canonical admission must reject duplicate
keys and numerically equal type substitutions rather than silently normalizing
them during the next phase transition. Activation-capable
entry points are removed before DKMS/module mutation. Every destructive transition,
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
For each upgrade fault-injection checkpoint, assert that the complete
pre-upgrade installed package state is restored: the package prefix tree,
DKMS-owned source tree, current-kernel module destination tree, and DKMS
registration marker. Compare regular-file bytes and modes, directory modes,
owner/group and link counts, symlink targets, special-file type/device
identity, and unexpected DKMS sibling images. Retain the direct byte-for-byte
CLI and installed-module assertions and require no remaining transaction
journal. The checkpoints intentionally share one fixture to detect drift after
earlier rollbacks; separate unittest methods still require fresh private
sandboxes. A negative control must mutate a non-CLI systemd payload and its
permissions, package-directory metadata, and an unexpected module variant
while the original CLI and module remain unchanged, proving that the
full-state oracle detects each change.
On a failing checkpoint only, retain bounded elapsed times for completed
checkpoints and bounded child output tails in private unittest diagnostics.
A timed-out package command must kill its private process group, including
fake DKMS descendants, and reap the direct package shell before the test
fixture can be cleaned up; the regression must prove that a descendant cannot
survive to write after the timeout. Timeouts must keep their original exception
identity for rootless first-failure classification; do not change deadlines,
fsync behavior or the checkpoint matrix to disguise slow durable storage.
The project-goals CI runs the same hermetic package fixture in an early
independent step before the combined rootless gate, so unrelated test failures
cannot mask packaging regressions. It neither replaces `make test` as the
official operator interface nor proves real-host module acceptance.
Incremental-build Makefile fixtures that compile or stage the primary manager
must include the committed fallback `src/kernel/swapz-build-info.h`; otherwise
they do not model the source inputs of the real checkout.

The primary qualification reader accepts only the root-owned
persistent qualification report. Qualification evidence is distinct from
same-boot lifecycle ownership under `/run/swapz`; it is not recovery state,
swapz extent metadata, or a reason to provision a separate recovery device.
The report must be a stable, single-link regular file with no group/world write
permission and at most 64 MiB. The C parser requires schema `swapz-test-results-v1`, matching
source and tested-commit SHAs, overall PASS, the RAM-backed qualification
scope, the same live x86_64 hardware-bound host digest, all five named stages with PASS and
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
metadata operation. The report must contain exactly one well-formed top-level
`kernel_release`; primary import and subsequent report reads compare it byte-
for-byte with the current x86_64 Linux `uname -r`. A missing, malformed,
duplicated or stale kernel release is BLOCKED and requires fresh exact-kernel
qualification. Before reading or replacing qualification state, production
and privileged qualification builds must acquire the shared global package/
mutation lock; the import then acquires the partition lifecycle lock from the
volatile runtime-state directory, preserving the global-before-partition order.
It accepts only a stable, non-writable regular input report that matches the
running build source, this x86_64 host identity, all five passing stages and the
live three-artifact hashes. It requires safe volatile runtime ownership state,
the partition lock, no active owner marker and no unfinished primary state,
while the qualification report bytes themselves are stored separately on
persistent root-owned storage. Replaced qualification evidence may be archived
under its SHA-256 name; no raw swap-header backup or recovery image is created.
This command does not prepare the partition, load the module, create a mapper
or enable swap. Rootless tests must exercise atomic store, repeat store,
prior-report preservation and refusal while an active marker exists.

The production-C rootless qualification-import contract must feed synthetic
five-stage PASS reports directly through
`swapz_primary_qualification_parse_json()`, with exact source and tested-commit
SHAs, matching three-artifact hashes, the public `swapz-host-v1` report schema,
and a deterministic digest of the current `swapz-host-v2` hardware-bound
identity layout. The v1 machine-id-only digest must be refused; the fixture
must never read or print private machine IDs or hardware UUIDs. Reject a changed
reported host digest, wrong source, stale tested commit, duplicate conflicting
key, missing artifact, non-PASS stage, wrong qualification kind, invalid syntax,
and trailing commas in objects or stage arrays. Each refusal must return
`EINVAL` without modifying the parser output; rootless import and lifecycle
entry points remain disabled, not simulated privileged success. Publication
of a report-only `[skip ci]` descendant does not turn a historical FAIL into
PASS or count as a fresh executable-source test.

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
unaligned payloads. The mapper-node publication retry predicate is pure
policy and must remain rootless-testable: only `ENOENT` may be retried; an
existing wrong node, `ENODEV`, permission failure, stale identity or I/O error
must fail immediately, and the total retry budget must remain bounded to at
most five seconds. The status-table parser must distinguish the
`DM_TABLE_LOAD` final-target `next=0` representation from the
`DM_TABLE_STATUS` aligned stride to the next target slot, and accept only the
exact one-target stride with bounded zero padding. Rootless direct-C coverage
must model the status response returned for an inactive loaded table, including
its nonzero final-target stride. The rootless build must prove that mapper create/remove
return `ENODEV` without setting any side-effect result. A strict production
userspace compile must also compile the guarded ioctl implementation. These
checks do not emulate kernel Device Mapper behavior or authorize a mapper on
the host.

The shared transaction-to-manifest admission check must require the matching
owner claim, allowed durable stage, exact stored manifest and live block-zero
SHA-256. The manifest stores only the digest of the immutable ordinary
`SWAPSPACE2` first page, never a backup copy. Rootless direct-C coverage must
accept a matching valid Linux swap header/geometry, reject digest changes and
malformed swap headers before mapper lifecycle operations, and prove no raw
write is attempted. These tests do not perform or authorize host block I/O.

Before future lifecycle enablement, interruption points after device creation,Before future lifecycle enablement, interruption points after device creation,
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
configuration rather than the first textual `#define`. Ordinary production,
owned-null_blk qualification and physical qualification may compile lifecycle
capability, but their runtime authorities are distinct and must fail closed.
The read-only primary plan and activation commands must use the same derived
compile-time-plus-runtime gate. `privileged_execution_enabled` must report
false for ordinary production until the boot-scoped authorization record
exactly matches current boot ID, clean build source SHA, configured PARTUUID
and target size; owned-null_blk qualification remains directly enabled inside
its private fixture; physical qualification is true only while its explicit
test-only runtime marker is exactly enabled. Ordinary production `prepare`
and `start` require that volatile activation authority. `stop` and
`recover` are deliberately different: token loss must not strand an existing
owned swap mapping. They may proceed without the volatile token only through
the exact durable transaction path, with root privilege, clean/current build
source, manifest source/target identity and the existing mapper/module/header
ownership checks. Private seams retain their original runtime gate for cleanup
as well. Ordinary production must
not read the physical qualification marker, and a private seam cannot
substitute for the production boot token. Comments and string literals
containing fake gate or syscall text never satisfy safety assertions.

Synthetic report-admission regressions must execute the actual package
source-clean guard (including its sanitized failure diagnostic and BLOCKED
disposition) against isolated generated-header bytes; finding a condition in
comments, matching a shell literal, or replacing the real rejection body with
a test-only exit does not establish executable coverage. Negative controls
include a different 40-hex source, dirty or malformed build cleanliness,
missing build identity, incorrect running-kernel release, malformed report
type, repeated or incomplete stage evidence, a failed required stage, and a
report whose hashes remain populated but whose overall verdict is FAIL.
The package's actual digest gate must compare final formatter/module/oracle
artifact bytes to the report, reject changed or absent bytes, and emit only
bounded expected/observed hashes and a read-only recapture action. A successful
old CI run or saved report for a prior source cannot become evidence for a
new owner-host execution. A separate relabeling negative control must keep the
release evidence's `source_sha` and qualified hashes current while setting only
the saved make-test `tested_source_sha` to a prior source, proving payload
validation rejects a current wrapper around stale qualification. The stale-owner
negative control must bind both source fields to that prior source while
evaluation targets the new source. The `overall=FAIL` negative control must
first leave the enclosing evidence status
as `PASS` to prove payload validation rejects the false promotion even with
all qualified hashes populated; a separate explicit-FAIL control preserves
FAIL precedence. These fixtures never write `test_results.json` or claim live
device qualification.

The project-goals current-attempt job census emits fail-only, bounded
`CI_NOT_QUALIFIED` diagnostics. Each refusal identifies the validated
`tested_sha` (or `invalid` for untrusted identity), the
`phase=exact-sha-census`, failing `gate`, `required` and `observed` states,
and a safe `corrective_procedure`. Keep the line at most 255 characters,
never include an Actions token, raw API exception or private path, and
never request a job manifest when checkout identity already mismatches.
The existing Make-interface CI job must also execute
`tests/tools/ci-failure-diagnostics-test.py` directly so its standalone
first-cause, redaction, producer-exit and retention-failure contracts cannot
silently diverge from the embedded Make-interface diagnostics. This is a
regression check inside the existing job, not another qualification stage.

Canonical CI release evidence contains exactly one row for each of the three
mandatory workflows, with distinct canonical positive signed-64-bit GitHub
run IDs. Extra, malformed, or duplicated rows cannot qualify the release even
when the required rows claim completed success. Every claim using a mandatory
loaded-evidence marker prefix must match its canonical grammar; a malformed
sibling claim cannot be ignored beside a valid marker. Canonical fault,
kernel-debug, resource-pressure and lifecycle markers are single-occurrence
evidence; duplicate PASS claims are incomplete.

The official rootless stage directly executes every mandatory Python contract
owned by that stage, including the owned-null_blk lifecycle qualifier and
`primary-real-swap-test.py`; the latter remains unit-only in GitHub Actions
and its privileged helper must block there.

The private real-swap source-admission protocol requires exact string types
for nonce and oracle SHA-256 fields; a JSON integer with identical rendered
hex digits is not a digest. Decoder recursion failures on bounded requests or
responses must become BLOCKED rather than escaping cleanup. Rootless negative
controls must prove that malformed pre-initial admission reaps its child, and
that source-transfer EPIPE reports the phase, errno, bounded exit/cleanup
disposition, and no private helper bytes or paths. None of these controls
authorize physical-swap execution. The source contract keeps an
explicit direct-suite registry and requires each path to exist and appear
exactly once in `test-rootless.sh`. The analyzer contract remains mandatory
through `tests -> suites test-all -> test-predictor -> test-anon-page-analyzer`
and is checked without duplicating its execution. Project-goal CI separately
pins the source-contract invocation and these discovery paths so removal or
renaming cannot silently reduce qualification coverage. `make test` remains
the sole qualification interface; `make fast_test` remains development-only.

Release-evaluator synthetic negative controls must remain rootless and model
the evidence fields emitted by the producer rather than inventing alternate
counters. Complete positive controls must also exercise the current
producer-shaped v2 campaign and independently measured per-cycle swap workload
so a fix cannot reject every release by default. The frozen parent policy
requires 14 pairs across its four workloads; the current v2 producer also
requires its two separately evaluated five-pair prospective-amendment cohorts.
Those amendment pairs never substitute for any of the 14 frozen pairs, and a
positive release fixture must carry the complete producer cohort. Development-only card evidence, including a source-bound fast-test
PASS, exact header restoration and an inactive final target, is never real-swap
or physical-acceptance evidence and cannot backfill an incomplete five-stage
`make test`. Development fixtures use the producer's `development_test_evidence`
field; real-swap preflight controls use only their persistent disposition,
phase and reason rather than borrowing development-probe restoration fields.
Real-swap no-traffic controls use `cycles[].workload` cgroup
swap, mapper use, swapz logical/physical READ/WRITE, lower-device byte, vmstat
swap-in/out and oracle mismatch fields. Campaign-completeness controls derive
required pair counts from the frozen workload map; a PASS-looking sealed
envelope with fewer required arms is incomplete proof. Stale source/artifact
bindings and contradictory PASS/BLOCKED summaries remain non-qualifying. Any
expected-failure reproducer for a known evaluator false-PASS is debugging
evidence only and must be reported as an unresolved release blocker; it never
upgrades acceptance.
Privacy leak checks use a separate ordinary regression, never an expected-failure
method, because `unittest.expectedFailure` would mask any assertion failure in
that method. Once repaired, the campaign-completeness, zero-traffic and
diagnostic-completeness regressions must likewise be ordinary negative controls.
Blockers must identify the first authoritative failed phase, evidence class,
required and observed workload/count or exact SHA-256/source binding, and
original disposition without copying private input paths or raw evidence.
Current-source, explicitly failed executions remain FAIL; unavailable,
incomplete and historical-source evidence remains BLOCKED.

`docs/handoff/production-readiness.json` is observational release evidence,
not a qualification result. Every current PASS must bind to the exact
production source and carry the evidence appropriate to its gate: clean build
state, qualified swapzctl/module/oracle hashes, all three required CI workflows,
exact-source owner `make test`, owned-null_blk lifecycle qualification, real
Linux swap-out/in, maximum-capacity plus measured RAM evidence, sustained
physical performance, lifecycle/deployment state, installed artifact identity,
armed cold-boot harness, and owner-observed reboot. Missing, historical, stale,
source-unbound, or structurally incomplete observations are BLOCKED or
IN_PROGRESS, never PASS; a current FAIL stays FAIL. The owner `make test`
evidence must carry the same swapzctl/module/oracle digests as the qualified
artifact evidence. Owned-null_blk lifecycle PASS evidence is source-bound but
uses a private test-seam control binary, so its swapzctl digest is not compared
to the production formatter. It must record `overall=PASS`, a valid retained
`evidence_sha256`, and the swapzctl/module/oracle hashes emitted by the
rehearsal qualification report. The private lifecycle-control hash is required only for
structural provenance; the lifecycle module and oracle hashes must exactly match
the qualified release module and oracle. Missing, malformed, non-PASS, or
module/oracle-mismatched lifecycle evidence is BLOCKED. Real-swap PASS evidence
must carry the installed qualified swapzctl/module/oracle digests observed by
the physical helper, the SHA-256 of the temporary physical execution control,
and an explicit
`installed_control_privileged_execution_enabled=false` observation made after
qualification import. The temporary control digest must be valid and distinct
from the installed formatter digest; otherwise the evidence does not prove the
destructive run used only the private seam while the production control stayed
runtime-locked. Those installed digests plus installed artifact identity must
match the exact qualified release artifacts. Real-swap, maximum-capacity/RAM and sustained-physical PASS evidence
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
exact partition byte size. The PARTUUID must use the same structural grammar as
the production primary selector: 8..64 total characters, at least eight ASCII
hex digits, single internal hyphens only, and no leading, trailing or consecutive
hyphens. Real-swap, maximum-capacity/RAM, sustained-physical,
lifecycle/deployment, armed cold-boot and owner-observed reboot PASS records
must bind that same tuple. Runtime major:minor is deliberately excluded because
it may change across attachment or boot; this is a consistency check and does
not claim PARTUUID plus size is cryptographic or physical-card uniqueness. A
retained old host snapshot must be labeled HISTORICAL and cannot become a
current release verdict.
Code/deployment readiness-for-owner-reboot is reported separately from the
owner-observed cold-boot result so automation never fabricates reboot evidence.
A summary `owner_observed_reboot: PASS` is insufficient for final release. It
must SHA-256 bind the exact persisted `swapz-primary-cold-boot-v1` report
written by the boot verifier, and the executable evaluator must ingest those
bytes separately. The retained report must independently confirm a distinct
armed/current boot ID, the exact release source and clean loaded module, the
authorized PARTUUID and partition byte size, the run-bound mapper identity and
capacity, one active mapper swap entry, healthy mapper/swap services, and zero
swapz or relevant-kernel error counters. The retained swap inventory must also
report at least one total swap entry, with a bounded nonnegative integer used
KiB count no larger than the mapper's reported swap size. Zero or malformed
total entries and impossible usage contradict the active mapper witness and
remain BLOCKED, even when the report's digest, source and target match. Other
unrelated swap entries are permitted. The canonical retained report field set
must exactly match the current boot verifier output. That contract includes the
mapper sysfs DM name and GC progress/reserve telemetry; release evaluation must
require the mapper sysfs name to be `swapz-primary`, canonical bounded
nonnegative GC counters (exactly `0` or nonzero ASCII decimal without leading
zeros), nonzero initial/current GC reserves, and current reserve no greater than
initial. Rootless release-evidence tests must compare
the producer report keys, evaluator whitelist, and synthetic fixture exactly so
producer/evaluator drift blocks the source contract rather than a valid owner
report. The evaluator must independently
recompute the maximum logical mapper sectors from the authorized partition bytes
using the production one-block header, segment alignment, reserve rule, u32
physical-index limit and independent 256-block foreground COW headroom; matching
report-side expected/actual capacity fields are not sufficient.
Missing, malformed, digest-mismatched,
source/target-mismatched or non-PASS retained boot evidence keeps
`COLD_BOOT_OBSERVED=NO` and the final release BLOCKED; it does not erase an
otherwise valid pre-reboot code/deployment readiness result. A reboot summary
can drive PASS only when it is current, exact-source/target bound, marked
observed, carries a strict UTC `observed_at_utc` timestamp, its `overall`
disposition matches PASS, and it SHA-256 binds the separately validated retained
PASS report. A reboot FAIL summary likewise cannot establish release FAIL by
itself. It must bind a retained `swapz-primary-cold-boot-v1` FAIL report from a
distinct observed boot, the validated arm record, exact current kernel,
source/module artifact and authorized target, at least one canonical failure
reason, and no incomplete reason. Missing, malformed, stale, wrong-source,
wrong-artifact, wrong-target or mixed FAIL/INCOMPLETE reboot evidence remains
NO/BLOCKED. A structurally incomplete reboot summary remains NO/BLOCKED rather
than fabricating an observation.
Owner `test_results.json` ingestion is strict: a qualifying PASS stage list
must contain exactly the five canonical stages in order, each with
`status: PASS` and an integer `exit_code: 0`; duplicate, reordered, missing,
extra, or internally contradictory PASS rows are BLOCKED. A fail-fast report
may contain only the canonical stage prefix through its first failed stage.
When that exact-source report has `overall: FAIL` and the first non-PASS row
has `status: FAIL` with a nonzero integer exit code, it is producer-proven
failed execution and the final release verdict is FAIL. A BLOCKED/INCOMPLETE
row, malformed/noncanonical prefix, absent failed row, or previous-source
report remains BLOCKED. The qualified-artifact object accepts only its status
plus formatter/module/oracle SHA-256 fields.
Package admission must enforce those JSON types and object keys exactly:
`false`, `0.0`, and `"0"` are not an integer stage exit code, and extra
artifact fields are non-canonical even when all three required digests exist.
A public admission rejection must name the invalid field, sanitized
`source_sha` and `tested_commit_sha`, expected and observed classifications,
and the required next `make test` action without exposing an absolute host
path. Every current PASS
release record must carry a strict UTC `observed_at_utc` timestamp, and each
required CI workflow PASS must carry one concrete positive run ID for the exact
release source. Required CI evidence must also bind a completed workflow run
with conclusion success; pending, failed or cancelled GitHub runs remain BLOCKED
even when the summary claims PASS. The official runner's embedded readiness
summary and the canonical standalone release evaluator must enforce this same
exact-source, completed-success and concrete-positive-run-ID contract. Run-ID
syntax checks must be non-throwing for pathological input and accept only
canonical positive ASCII decimal identifiers, never Unicode digits or
leading-zero text. A rootless mismatch regression must assert
that the blocker names the affected workflow and the exact-source condition;
it must not depend on stale abbreviated diagnostic wording. The
`unresolved_critical_issues` release record must carry a real JSON integer
count exactly equal to zero and an empty `issues` list;
booleans, strings, negative values, null, nonzero counts, or a zero count paired
with listed issues are BLOCKED.

The executable evaluator's process success is stricter than the pre-reboot
readiness fields: it returns 0 only when the full `release_verdict` is PASS,
which requires code PASS, deployment PASS and a current owner-observed cold-boot
PASS backed by that retained report on the same authorized target. It returns
1 for a source/receipt-bound producer-proven failed execution: an exact-source
owner fail-fast FAIL, terminal real-swap FAIL/COMPLETE, sealed physical audit
FAIL, or current owner-observed reboot FAIL. Missing, malformed, stale,
nonterminal/interrupted or producer-BLOCKED evidence keeps the release verdict
BLOCKED and returns 2. Therefore automation can use the command exit status as
a final-release gate without confusing “safe to perform the owner reboot” with
“release qualification complete.”

The private `tests/tools/evaluate-production-readiness.py` evaluator is the
executable form of this release-evidence contract; it is not a new operator
command and never performs privileged work. It must derive readiness rather
than trust summary PASS fields. The legacy summary helper in
`tests/tools/run-tests.py` is observational only: because it does not open the
retained real-swap or physical-campaign artifacts, it must never promote
`real_linux_swap`, `maximum_capacity_and_ram`, or
`sustained_physical_performance` from summary PASS to release PASS. Those
summary PASS values are BLOCKED until the canonical evaluator validates the
persistent evidence bytes. Strict JSON rejects duplicate keys,
nonfinite/overflowing numbers, and more than 128 nested JSON containers before
decoding, so malformed depth cannot consume unbounded parser/validator recursion.
Nested duplicate-key diagnostics must identify the duplicate-key schema class
without echoing attacker-controlled key text. Forged physical-campaign source
bindings must report expected-versus-observed identity classes, never raw
campaign source SHAs, target identifiers or private filesystem paths.
requires a FROZEN canonical production-acceptance policy, hashes the exact
policy bytes, binds owner `make test`, all three required CI workflows
(`Native kernel-C project-goal regressions`,
`Experimental swapz production C qualification`, and
`Systemd and package production-readiness`) and all qualified artifacts to one
exact synchronized `main` SHA, independently cross-checks
formatter/module/oracle hashes for owner, real-swap and installed-artifact
evidence, and requires owned-null_blk lifecycle evidence to carry an exact-source
PASS result, a valid retained evidence digest, and production-matching module and
oracle hashes while allowing its private test-seam formatter hash to differ.
A synthesized `real_linux_swap: PASS` record is never sufficient: code
readiness must also ingest the strict crash-persistent
`swapz-primary-real-swap-evidence-v1` file emitted by the physical helper,
SHA-256 bind those exact evidence bytes from the release record, require final
PASS/COMPLETE disposition, and independently validate its nested
`swapz-primary-real-swap-v1` result. Envelope and nested result must agree on
exact release source, frozen policy digest, owner-report digest, qualified
installed artifact hashes, current source-controlled helper/oracle digests,
valid private execution-control digest, frozen workload/cycle values, distinct
transaction run IDs and Linux swap UUIDs, and durable COMPLETE for every
required cycle. They must also bind the producer's exact physical-control input
inventory to the current source-controlled bytes, including the acceptance
manifest and the pinned authorization-snapshot digest; checking that digest
does not promote the historical readiness snapshot into current qualification.
Every cycle must prove the loaded module's exact source/clean/physical-backing
provenance and complete cycle-wide safety telemetry, including monotonic
sampling and the frozen minimum-MemAvailable floor. The boot-scoped `target_device` major:minor recorded by the
real-swap helper is diagnostic rather than part of the cross-boot canonical
target tuple, but it must be a valid major:minor and the persistent envelope
must exactly match the nested PASS result; malformed or mismatched device
identity is BLOCKED. Missing persistent physical evidence is BLOCKED.
For each required real-swap cycle, the release evaluator must independently
require the producer's two concurrent-oracle reuse rounds and the frozen
minimum 128 MiB swap charge and logical swapz READ/WRITE evidence per round,
not merely zero oracle mismatches or durable COMPLETE. Every round must bind
the dedicated cgroup's swap charge to exact mapper use, nonzero
`pswpout`/`pswpin`, physical swapz READ/WRITE activity, and host-visible
backing-device sector/byte counters that cover the reported physical traffic.
It must check verified page/byte geometry, digests, zero mismatches/OOM,
release of the exact mapper slots, coherent cycle aggregates and witnessed
normal swapoff-before-removal order. Missing or zero traffic is BLOCKED even
when a source-bound retained artifact claims PASS. An exact-source terminal
persistent real-swap `FAIL` at phase `COMPLETE`, bound through the current
receipt, owner report, target, frozen policy, helper/oracle and physical-control
inputs, is a proven failed execution. The producer's initial/interrupted
default FAIL disposition, terminal BLOCKED disposition, stale source or
unbound artifact remains BLOCKED rather than being upgraded to FAIL.
Current PASS physical records bind the normalized lowercase PARTUUID plus exact
partition byte size and the frozen policy SHA-256. A synthesized
`sustained_physical_performance: PASS` record is not sufficient: release
evaluation must also ingest the sealed
`swapz-performance-campaign-evidence-v1` artifact, SHA-256 bind those exact
bytes from the release record, require exact source and pair-source consistency,
v2 PASS qualification, the same authorized target, an exact MATCH between
the accepted qualification-pair lower identity and the campaign host snapshot,
STABLE host identity with quiescent admitted-device boundaries, and the exact
current policy, prospective-amendment, campaign-evaluator, evidence-sealer and
metadata-RAM-validator digests. Its
host/summary/pair artifact manifest must be structurally complete and internally
count-consistent. The release evaluator must independently require every
frozen parent-policy workload with exact pair counts (5, 5, 1, 3; 14 total)
and must also require the complete current v2 producer cohort. The current
prospective amendment contributes two separate five-pair workloads, so the
current v2 producer has 24 pair artifacts in total; amendment pairs are
separately identified and can never replace a missing frozen pair. Pair
artifacts require unique names and digests, unique per-workload pair IDs and
indices, exact counterbalanced order and PASS/non-excluded disposition. The
campaign's self-reported `record_count`, aggregate PASS status and exact JSON
digest are necessary but do not establish missing arms or an incomplete
workload cohort. A shortened or inconsistent campaign is BLOCKED even when its
internal envelope and digest agree. The producer's `physical_evidence_audit` is itself untrusted retained
evidence. Release evaluation requires its exact current field set, admitted
source SHA and PARTUUID, top-level qualification-status binding, frozen claim
boundary, measurement authority, and one exact required/attempted/accepted
count record for every current producer workload. A PASS audit additionally
requires zero retained/omitted diagnostics, no first failed phase/evidence and
complete accepted counts; an older, partial, extra-field, wrong-source,
wrong-target or count-mismatched audit remains BLOCKED even when the surrounding
campaign claims PASS. For every workload, the audit's `accepted_pairs` must
never exceed the retained PASS/non-excluded pair-manifest count; a scalar that
counts an EXCLUDED pair as accepted is contradictory evidence and remains
BLOCKED. The count may be lower when analyzer-level screening makes an otherwise
immutable PASS pair unusable; such unrelated incompleteness must not erase a
separately authenticated producer or measured FAIL.

A source/target/policy/tool-bound campaign can establish producer-proven FAIL
only from the current audit's retained first-failure witness. The first failure
must match exactly one retained diagnostic with its workload/pair/arm/metric
identity; duplicate same-identity rows are contradictory even when one row is
otherwise canonical. That unique diagnostic must be FAIL and either (a) be an authenticated
non-setup `arm.verdict` producer FAIL with the same workload/pair/arm and one
matching EXCLUDED pair-manifest entry with a producer-recorded
measurement phase and retain a nonempty original producer error; the error
stays in the immutable pair artifact and is never copied into public diagnostics.
Preflight, fill, warmup, teardown and publication failures remain BLOCKED unusable
evidence. Or (b), the witness may be a
`qualification.decision_status` FAIL for a complete
accepted measured cohort. That measured decision must retain the producer's
exact diagnostic field set, expected PASS, null observed value, and canonical
verified-measurements-failed reason. A contradictory or duplicate diagnostic or
arm-only producer-status field cannot authenticate the cohort FAIL: report the
qualification producer phase, expected/observed evidence classes and unavailable
original measurement error without exposing private identifiers. Before either witness can drive release FAIL, the
retained pair manifest must have type-strict PASS/EXCLUDED dispositions and
unique workload pair indices, pair IDs, artifact basenames and SHA-256 digests,
with the prescribed counterbalanced order.
The audit qualification status and campaign qualification status must both be
`FAIL_OR_INCOMPLETE`. A hand-edited FAIL diagnostic paired with an all-PASS
manifest is synthetic logic evidence only and remains BLOCKED. A missing or
premature seal, contradictory qualification target, stale source, malformed
audit identity/counts, BLOCKED/UNAVAILABLE evidence or incomplete failure
witness likewise remains BLOCKED. Failure authentication also requires a
STABLE host with the producer's exact current stability-check field set, every
check true and empty failed-checks. Both admitted-device boundaries must carry
the exact current major:minor/swap/mount/holder/quiescence fields, bind the
qualification lower device, and prove empty swap/mount/holder inventories. The
source/target/policy/digest-bound release receipt must be current and its
observation timestamp must not predate the campaign seal; a stale or
identity-mismatched receipt is BLOCKED even when the retained campaign contains
a valid-looking FAIL. Type-malformed nested audit witnesses, cohort counts and
pair identifiers must fail closed as BLOCKED without raising. Failure
diagnostics identify the earliest receipt/seal/target/host/audit gate, expected
versus observed receipt and campaign source/target identities, the campaign
digest and relevant pair count, and why FAIL versus BLOCKED was selected.
The existing five-argument private campaign-validator call remains supported
for structural/measurement-only callers and loads tracked policy authority,
but it does not establish release completeness. `evaluate_release` supplies
the validated policy as the sixth argument and is the path that enforces the
14 frozen pairs, complete current v2 producer cohort and physical-audit release
gates. Performance-cohort incompleteness or an authenticated performance FAIL still
blocks code readiness, but neither erases an independently valid
source/target/policy/trace-bound maximum-capacity/RAM measurement from the same
sealed artifact. The five-argument structural/measurement validation path
therefore does not require campaign/qualification PASS; it still requires the
sealed source, target, tooling, host, trace and artifact structure needed for
the capacity/RAM measurement itself. That gate retains its own
within-limit/over-limit disposition. Conversely, missing capacity/RAM evidence
does not erase a separately authenticated performance FAIL. Missing or stale
sealed campaign evidence is BLOCKED.
Full-capacity evidence must come from that same sealed campaign: the sealer
derives maximum logical pages/bytes and measured target/metadata peak RAM from
the accepted `sd-high-occupancy-churn` swapz arm, and a PASS campaign is invalid
without that tuple. The same sealer now rejects a smaller logical mapper
even if a plausible capacity/peak scalar is provided: capacity is independently
recomputed from the target partition, its protected SWAPSPACE2 first page, GC reserve,
segment alignment and foreground headroom. Rootless synthetic traces never
qualify the host. A resource PASS must carry source-bound and mapper-UUID-bound
serialized loaded-host samples from the conservative whole-host measurement
above: exact 100 ms cadence declaration, boot identity, UTC and monotonic
timestamps, raw \`MemAvailable\`/\`SUnreclaim\`/\`VmallocUsed\` KiB
counters with an exact unit declaration, mapper-presence state, one second of
target-absent baseline, initialization,
steady and GC observations, ordinary teardown, and at least two seconds of
target-absent recovery. Each adjacent monotonic sample interval must be
50-150 ms and the mean cadence across the full trace must remain within
10% of 100 ms; a 100 ms label on systematically slower samples does not
qualify. The first-to-last UTC elapsed time must also agree with the monotonic
elapsed time within 500 ms, so per-sample wall-clock tolerance cannot accumulate
into a fabricated host-snapshot chronology. A repeated or backward adjacent UTC
timestamp is a clock-order failure, not proof of missing samples; diagnostics
report the signed UTC interval, corresponding monotonic interval, first failed
phase and unavailable peak without inventing an omission count. The last second of mapper-absent
teardown samples must recover the
pre-constructor baseline **median** for `MemAvailable` (no lower) and for
`SUnreclaim`/`VmallocUsed` (no higher), with integer-exact half-KiB median
arithmetic. A single extreme baseline outlier cannot excuse persistent
post-removal memory use; failure to recover blocks qualification.
Initialization must precede the exact sustained swapz
arm, steady/GC samples must fall inside that arm's monotonic interval, and
teardown must follow its completion; a correctly shaped trace from elsewhere
in the same boot cannot qualify. The phase-order contract is
baseline -> initialization -> sustained -> teardown. Within the sustained
stage, `steady` and `gc` labels may interleave because target GC can recur
during a long workload; requiring all steady observations to precede all GC
observations is a false BLOCKED result, not stronger evidence. Sustained
telemetry preserves absolute monotonic interval bounds. Every RAM sample
labeled `gc` must overlap an interval where at least one exported target
counter among `gc_wall_ns`, `gc_victims` or `gc_pages` actually advanced;
a caller-supplied GC phase label without measured target GC activity is invalid. The sealer derives the
peak from those raw counters, stores the derived summary, and also seals the
sustained arm's absolute start/end plus only the positive-GC telemetry windows.
The release evaluator independently recomputes the RAM summary and revalidates
the phase/GC chronology against that compact arm binding; a campaign cannot
drop the pair files and thereby lose the RAM-to-workload chronology check. It must not trust an asserted per-sample
"target RAM" byte count or a replay-time peak scalar, because this whole-host
method is conservative rather than exact target allocation attribution. Since
mapper teardown happens after the replay arm is written, the serialized
loaded-host sampler must publish a separate, immutable post-teardown JSON
artifact using the canonical JSON evidence writer. The campaign sealer
takes `--metadata-ram-trace` on its `seal` subcommand, verifies canonical bytes
and SHA-256 provenance, checks the boot ID against both host snapshots, and
requires sample timestamps within the host snapshot window. The release
evaluator checks the sealed trace against its artifact size and digest. A scalar embedded in an early replay pair cannot substitute for this later
artifact; zero or absent is acceptable diagnostic state, while a nonzero scalar
that contradicts the derived host trace is invalid. Missing phases, inconsistent
timestamps, raw-counter/summary mismatch, malformed provenance, mapper lifecycle
ambiguity or unrecovered teardown block the campaign and the release evaluator,
even if the supplied campaign digest was recomputed. The sealed host-memory
binding must also reject any `SUnreclaim` sample greater than independently
observed host `memory_total_bytes`, converting the raw `kB` integer with
checked bounds. The snapshot producer obtains `memory_total_bytes` by
multiplying the integer `MemTotal` `kB` counter by 1024, so the sealed value
must be a positive unsigned-64-bit multiple of 1024; a sub-KiB remainder is
malformed/BLOCKED evidence, not extra measurement precision. Unreclaimable
slab is physical RAM; `VmallocUsed` measures virtual address space and must
not be subject to that physical bound. Keep the exact per-field physical
bounds on `MemAvailable` and `SUnreclaim`, but do not derive an exact
`MemAvailable + SUnreclaim <= MemTotal` invariant. Linux reports
`MemAvailable` as an estimate assembled from independently changing free,
file-LRU and reclaimable-kernel counters, and `/proc/meminfo` snapshots
that estimate and slab counters through separate VM-stat reads. The values
are therefore not an atomic additive partition of `MemTotal`. A synthetic
fixture whose two counters are each in range but whose arithmetic sum exceeds
the host total must remain acceptable to the host-binding validator; that
fixture is parser semantics coverage, never physical RAM qualification. Reject
a malformed or indented second required meminfo counter instead of silently
ignoring contradictory values. A duplicate required counter with spaces or
tabs inserted before its colon, or a required counter truncated after its
name, is malformed even when a valid copy precedes it; unrelated meminfo names
remain ignorable. Rootless regression fixtures must retain a valid positive
control and reject a deleted low-MemAvailable peak observation even if the
remaining sample count still meets every phase minimum: the 200 ms gap violates
the unchanged 50-150 ms adjacent-sample bound. Cadence and missing-phase
diagnostics identify the first failed phase and a bounded minimum missing-sample
count. At a gap crossing phase labels, the earlier observed phase is the first
affected phase and the following observed phase must also be named. That
incomplete trace has peak RAM unavailable, never the lower surviving minimum.
They must not invent an exact missing-sample count from elapsed time:
given the permitted 150 ms maximum adjacent interval, a 300 ms observed gap
proves at least one missing observation, not exactly two.

A rejected RAM trace, sustained-arm chronology or sealed-host binding
must preserve the first failure's field/phase diagnostic and explicitly report
`peak_ram_bytes=unavailable`, exactly once. This includes malformed or
incomplete sustained-arm telemetry rejected while extracting its compact RAM
binding, before later trace-to-arm revalidation. Missing counters, incomplete
sample counts, short baselines and unrecovered teardown must not leave a
favorable peak implied by surviving observations. Rootless coverage must invoke
missing-arm extraction directly before later trace binding and, separately,
retain a sample-derived over-limit value after synthetic source, mapper, host
and arm binding; that synthetic value verifies classification semantics only,
never physical-host qualification. This classification does not relax the
frozen cadence or its conservative minimum-missing-samples bound.

A trace that labels itself as synthetic/rootless must not pass the loaded-host
capture/scope declarations. Correct declaration strings alone cannot
authenticate a capture: immutable trace hashes, exact source, host boot,
mapper and sustained-arm bindings, and actual serialized Codex collection
remain independent requirements. Capacity and frozen RAM-ceiling decisions
remain in the campaign sealer and release evaluator; isolated trace validation
cannot report observed physical capacity or an unseen true peak.
Report a malformed sample's index, precise
field and expected/observed numeric bounds without echoing arbitrary evidence
strings. An exact-mapper mismatch must identify the `mapper_uuid` field
without printing the supplied identity. Such contradictions are unavailable/BLOCKED evidence, not a measured
target failure; only a properly validated over-ceiling loaded-host peak is
a genuine measured RAM FAIL. The sealer must retain the exact validated
`peak_ram_bytes` in the existing `capacity_and_ram` tuple even when it is
above the frozen ceiling; it must not convert that measurement to unavailable
or duplicate the acceptance threshold/status into an unvalidated campaign
field. Missing, contradictory, unverified, or non-maximum geometry leaves that
tuple unavailable, and an otherwise PASS campaign cannot seal it as measured
acceptance. The campaign's `campaign_status` describes qualification of the
physical pairs, not the independent RAM ceiling: the release consumer checks
the raw trace/host/arm bindings and independently compares the sealed peak with
the exact frozen policy, rederiving `MEASURED_WITHIN_LIMIT` or
`MEASURED_OVER_LIMIT` rather than trusting a caller-supplied acceptance
label. Release verdicts may remain `BLOCKED` for incomplete independent
gates; neither campaign PASS nor release receipt PASS overrides a measured RAM
FAIL. Sealer BLOCKED diagnostics must include phase, metric, exact limit, a safe
invalid/unavailable category and next prerequisite; nonphysical unit fixtures
never establish loaded-host measurement.
Neither a synthetic control nor the 740 MiB
index-only capacity estimate can become physical RAM acceptance. The focused
synthetic metadata-RAM validator regression is part of the official rootless
`make test` discovery path. `tests/tools/test-rootless.sh` must execute
`tests/runtime/benchmark/metadata-ram-evidence-test.py` exactly once, and the
source-contract mandatory-suite list must enforce that registration; adding a
test file that no rootless entry point executes does not establish regression
coverage. The serialized Codex
loaded-host collector remains a separate required qualification; an
unbound scalar from `--metadata-and-target-peak-ram-bytes` alone is not a
resource PASS.

The `maximum_capacity_and_ram` release record must SHA-256
bind the same campaign bytes and exactly match the sealed logical capacity and
peak RAM. Peak RAM must remain no greater than the frozen
`metadata_and_target_peak_ram_bytes_max`. Current code readiness also requires
zero explicitly recorded unresolved critical correctness/ownership/race issues.
Deployment readiness additionally requires lifecycle/deployment PASS with a
valid retained evidence SHA-256 digest, exact installed artifact hashes, and an
armed cold-boot harness whose release record SHA-256 binds its separately
validated persistent arm evidence. Owner reboot
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
For the native flush-ordering contract, a data-bearing
`WRITE|PREFLUSH|FUA` upper BIO must first drain earlier work and complete the
lower preflush successfully, then wait for its one owned lower data WRITE
completion, then complete the required lower FUA flush before publishing its
generation or acknowledging success. Failure at any stage propagates the
original lower errno, preserves the prior authoritative mapping, latches
terminal failure and bars later drain/retry from creating a success ACK. A
zero-sector Linux upper flush is `REQ_OP_WRITE|REQ_PREFLUSH`; with no data,
only PREFLUSH is meaningful, so native fixtures must not invent a separate
empty-FUA durability step. `REQ_OP_FLUSH` is not a valid upper BIO opcode.
Rootless fixtures must check separate flush submissions/success/failure counts,
the exact single data-BIO completion owner, duplicate notifications of that same
completion without inventing independently completed BIOs, explicit
durable-publication counts, and a fresh upper retry completed from the latched
terminal error without additional lower I/O. The preflush-fence negative
control must continue through data completion and the FUA gate far enough to
demonstrate a forbidden successful upper ACK, rather than stop merely because a
failed preflush allowed data submission. Their finite faults are not
loaded-kernel, device-cache, KASAN or physical-media evidence.
Ordinary DM suspend/drain does not synthesize a cancellation errno for accepted
BIOs. A PREFLUSH boundary first joins every older detached lower WRITE; if that
callback fails, its lower errno prevents the lower preflush from being issued.
Once PREFLUSH itself is issued, no older lower callback owner remains, so a
failed preflush followed by an older callback failure is not a production
schedule and rootless fixtures must not fabricate it. Required FUA is
synchronous and detached asynchronous writes do not carry FUA. Delayed-FUA
coverage must observe the synchronous lower flush while that call is still
outstanding and prove no ACK or generation publication occurs before its
return. For a non-FUA detached WRITE, drain may overlap the final callback; the
callback elects its lower errno before publishing completion, while an
independent terminal failure uses the same first-failure latch as production.
If the callback wins that election, later failures cannot replace its errno.
If another terminal failure wins first, the current run may still report its
own later lower callback errno, while a fresh upper retry observes the already
latched target errno. Repeat drain and retry must not issue additional lower
I/O. On failure, report submission phase, expected/observed completed lower
blocks, original lower errno, expected/observed ACK errno, publication/generation
counts, explicit generation/ownership category, safe disposition and outstanding
lower/upper completion owners. Expected completed blocks come from the scenario;
observed completed blocks must derive from the callback's actual completion/error
state, never the expected fault. These rootless models do not claim a loaded callback
race or real-media cache persistence.
Mandatory Python qualification suites must remain syntactically valid; a path that exists but cannot execute does not satisfy discovery coverage.


### Runtime systemd health and non-hibernation regression

The isolated systemd fixture must exercise the runtime-health helper and unit
without reading or changing host swap state. Cover exact mapper/run/backing
identity, foreign mapper rejection, active swap inventory and capacity,
primary mapper partition type, priority -1 and DM-derived usable capacity
(including a healthy second read that must not erase a first-read failure),
path-free journal diagnostics,
configured backing-path disappearance as a hard failure, monitoring-command
failure as degraded evidence, low-noise unchanged polling, kernel/systemd
telemetry, and sustained GC pressure without progress. A confirmed nonzero
canonical DM `error` must produce a bounded `target_terminal` / `first_error`
phase/check/expected/observed/command-status diagnostic containing the signed
kernel errno and a read-only next step. Rootless coverage must accept zero and
negative Linux errno values from -1 through -4095, reject positive, out-of-range
or noncanonical error tokens as malformed telemetry, explicitly reject -4096 so
digit-length shortcuts cannot bypass the errno ceiling, and prove that `failed=1` still yields
FAIL without fabricated first-error attribution when the error token is
malformed. Missing or malformed terminal errors must never be reported as
confirmed first errors. A nominally active
oneshot mapper must have `SubState=exited` and an active passive swap unit
must have `SubState=active`; synthetic contradictory substates must fail even
with successful `Result`, while a failed substate probe must degrade with its
original exit code and inferred-versus-observed attribution. Successful blank or
multiline substate output must degrade as observed malformed telemetry with
command status zero. Passive `is-enabled` coverage must admit `static`/0 and
`disabled`/1, and degrade mismatched state/exit pairs while preserving the
observed exit. The sustained-GC fixture
must increase pressure/no-headroom counters across consecutive polls while
holding victim/page progress constant; reaching the existing stall threshold
must latch runtime health FAIL, emit one
`SWAPZ_RUNTIME_STOP_REQUIRED=1 reason=sustained_gc_stall
action=normal_primary_stop_required` marker, and continue observation without
executing swapoff, mapper removal, or `swapzctl primary stop`. Cold-boot verification
must independently derive maximum mapper geometry from the selected backing
bytes using the production reserve rule plus one 256-block foreground COW
headroom segment. For the current-card geometry it must accept 216,641,536
logical sectors and reject the exact retired zero-headroom 216,643,584-sector
geometry with `mapper_logical_capacity_mismatch`. The calculation must also
reject a physical-block geometry outside the kernel's `swapz_u32` address
domain. Target health failures must remain observable rather than causing the
monitor service to restart the primary lifecycle; only monitor-process failure
is eligible for `Restart=on-failure`.

Effective systemd unit qualification must inspect the merged deployed
configuration, not just the vendor unit source. Rootless fixtures must layer
generator-authorized selected-PARTUUID device/swap dependencies with
administrator configuration using systemd's effective precedence rules.
Repeated scalar settings are last-wins; Exec/filter/install lists honor their
documented empty-assignment resets, while unit dependencies (including
RequiresMountsFor= path dependencies) are additive in drop-ins and cannot be
removed by an empty assignment. Model top-level type and dash-prefix drop-ins,
lexicographic application, and same-name specificity/load-path precedence,
including an exact administrator drop-in shadowing a normal generator
fragment. Also exercise a higher-priority whole-unit replacement, because
that can remove dependencies which a drop-in cannot. Security-sensitive
capability and syscall-filter group changes must fail closed rather than
assuming the current systemd/kernel can enforce every syntactically valid
sandbox directive. Reject overrides that relax
observer @swap/@module denial, grant observer lifecycle commands, remove
mapper DM/module/swap capability, reorder activation guard -> preflight ->
recover -> prepare -> start, change the sole primary stop/swapoff owner,
remove recovery-mount or selected-device requirements, weaken timeouts, or
activate the passive swap alias. Rootless vendor-unit and normal-generator
shadow fixtures must require `DefaultDependencies=no` on the passive mapper
`.swap` view and reject an effective override to `yes`, so systemd cannot add
an `umount.target` shutdown stop and issue a second `swapoff` after a failed
native manager stop. Report the effective directive, required
value, observed override basename and safety consequence without host paths.
If a whole-unit replacement removes a vendor contribution from an additive
directive that a surviving generator fragment also augments, attribute the
missing contribution to the replacing unit rather than the generator.
systemd-analyze verify contributes syntax/dependency evidence when available;
its absence is INCOMPLETE, not PASS, and its success is not proof of runtime
sandbox support. The boot observer must atomically claim the single-use preflight authorization
out of swapzctl's canonical runtime pathname before any slow evidence
collection; it validates only that non-authoritative claimed file. A successful
claim must therefore remove the canonical pathname before observation proceeds;
every terminal path must leave that canonical authorization non-authoritative
after PASS, FAIL or INCOMPLETE, and after an interrupted attempt. Armed
observations with a missing, duplicated or mismatched claimed token must FAIL
rather than pass. A claim rename or directory-sync failure preserves the
original command exit status, refuses PASS, and immediately falls back to
canonical revocation/invalidation. Shell failure branches must capture `$?`
before any assignment or diagnostic preparation, and the rootless fault fixtures
must assert the injected exit value rather than accepting a generic failure. Final cleanup removes the claimed secret and
rechecks the canonical pathname; failure to remove the claimed file is FAIL but
cannot make that noncanonical file activation authority. An observer interrupted
by HUP/INT/TERM must explicitly exit through this cleanup (an EXIT-only trap is
insufficient for POSIX sh), report the signal exit status and unknown retention
of partial evidence, and never claim PASS. During kernel-journal collection,
the bounded timeout must be an owned background supervisor with an interruptible
shell wait. Rootless fixture discovery may check `timeout` and the Ubuntu GNU-
prefixed `gnutimeout` under `/usr/bin:/bin`, but it must verify the selected
binary identifies itself as GNU coreutils; uutils or another implementation
must not satisfy this requirement. Run GNU timeout in foreground-command mode
so the supervisor remains
in the observer process group and can reap its direct journal child after
kill-after escalation; do not put the supervisor in the child process group
that escalation may kill. A signal received between asynchronous launch and
capturing `$!` must be deferred until the timeout PID is owned, preserving the
first signal reason. On interruption signal only that owned timeout supervisor,
wait for the supervisor's status, then revoke authorization. Rootless signal
fixtures must signal the observer process directly so the observer's handler,
not a process-group broadcast, owns supervisor termination. The reported
`timeout_wait_status` is the wait status of the observer's direct GNU `timeout`
supervisor, not the raw `journalctl` result. GNU `timeout` can return 124 both
when its watchdog expires and when an external TERM is forwarded to its
command; status 124 alone proves neither cause. For the ordinary direct-TERM
regression, a test-only wrapper must verify that production requested its
fixed `5s` deadline, then run the real GNU `timeout` with an extended test
deadline so the watchdog cannot win the fixture race. Before signaling, prove
that the timeout process is live, directly owns the journal process, and both
remain in the observer's process group. Require the observer's original
128+signal exit status (143 for TERM), the explicit `signal=TERM` and
`process_ownership=owned_timeout_child` record, `timeout_wait_status=124`
or `timeout_wait_status=143` (the latter is the observed status when the
supervisor exits on external TERM), no PASS, complete timeout/journal cleanup,
and revoked one-use token. The extended fixture deadline and live
process-parent/group proofs must exclude a watchdog-only timeout. The
TERM-resistant journal control must report `timeout_wait_status=137` after
the owned timeout performs its bounded KILL escalation. The fail-only signal
diagnostic must retain the original 128+signal status even if token cleanup
and its EXIT retry fail, and identify signal, process ownership, timeout wait
status, token disposition, cleanup phase/status and retained evidence without
runtime token paths. Rootless regression must trace parent/PGID and output FD
ownership, assert prompt exit and no surviving timeout/journal process for both
ordinary TERM and a TERM-resistant journal that requires bounded KILL escalation,
inject cleanup failure, and reject a repeated observation without a new
preflight. Rootless systemd fixtures must remove inherited `MOCK_*`,
`SWAPZ_PRIMARY_TEST_*`, and `SWAPZ_PRIMARY_SYSTEMD_TESTING` controls before
building child environments, then explicitly reintroduce only the controls
owned by that fixture. Preserve unrelated host environment such as PATH,
locale, and temporary-directory selection unless the fixture explicitly binds
them. A failed canonical unlink may safely
invalidate a still-owned regular 0600 single-link token without following
substituted symlinks; preserve the original unlink error and refuse PASS even if
invalidation is impossible. An active oneshot mapper requires SubState=exited
and the passive active .swap requires SubState=active; unknown substates are
INCOMPLETE and contradictions FAIL.
Each malformed kernel-status observation must reissue its own token, then
verify that non-PASS handling revoked it. A further rootless boot-verifier
negative control must inject nonzero `dmsetup info`, `table`, and `status`
exits carrying positive-looking stdout, proving that the failed command's
bytes never certify PASS. A dual-fault case retains the original first
failed-probe exit and phase. Multiline otherwise valid DM UUID output is
ambiguous rather than a trusted first line. Passive `systemctl is-enabled`
status/text contradictions (`static`/nonzero and `disabled`/zero) must
BLOCK; the documented `disabled`/1 combination remains admitted. Reissue
the one-use preflight authorization after each observed FAIL/INCOMPLETE and
verify canonical and claimed token paths are absent. All controls are
private and rootless; none starts or stops swap. If `systemctl is-enabled`
returns an unrecognized state, its raw output must not be echoed into public
diagnostics: report `observed=untrusted`, retain the exit status, and classify
the result as INCOMPLETE. The fixture must cover command statuses 0, 1, 2 and 3,
an unexpected status, contradictory state/status pairs and empty output. An
arbitrary private sentinel must be absent from diagnostics while being
classified as `observed=untrusted`; none of these controls may certify PASS.

Boot-verifier contracts must prove that a retained package transaction is
detected by both preflight and post-boot observation after selector parsing.
Malformed kernel-status cases must obtain a fresh preflight authorization for
each observation because every observation consumes or revokes that one-use
token, including an `INCOMPLETE` result. Do not weaken the expected status to
hide a missing authorization or a journal that the verifier failed to find.

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
cannot manufacture observed cold-boot evidence. The retained v1 report must
have exactly the verifier's fixed field set, retain a removable parent with at
least one stable serial/WWN identity, and carry the exact 12-field production
DM table bound to the computed logical sector count and the observed selected
target major:minor. Unknown/missing fields, a substituted lower device or a
self-declared PASS with inconsistent mapper geometry are BLOCKED. Rootless
readiness parser regressions must assert exact duplicate-key refusal for
known and unknown keys, reject malformed or non-lowercase-ASCII keys,
and bound oversized identifiers and inputs. Syntactically valid but
non-canonical fields remain BLOCKED; parser diagnostics must state the
refusal without echoing private evidence values or unbounded key text.
Before deployment may be
declared ready for an owner reboot, the canonical evaluator must also ingest
and SHA-256 bind the exact durable `swapz-primary-boot-arm-v1` record. That arm
record must have its fixed canonical field set and bind the current owner
kernel, release source/module bytes, authorized PARTUUID/size, removable parent
and at least one stable serial/WWN identity. Final cold-boot PASS must
cross-bind the observed report's `armed_boot_id` and stable selected-parent
attributes to that same validated arm record; a summary `armed=true` bit alone
must never make `PRODUCTION_READY_FOR_OWNER_REBOOT` PASS.


The package fixture retains its ordinary 15-second operation watchdog. Only
known compressed-DKMS fixture variants (.zst, .xz and .gz) receive a finite
60-second budget: the controlled .xz witness delays exactly one Python fsync
for 16 seconds, then calls the real fsync and must preserve the original
successful uninstall status, final absent state and empty uninstall journal.
The wider compressed budget allows multiple durable transaction boundaries
without weakening unrelated package tests; it is a test watchdog, not a
production latency promise. The independently one-second nonterminating
fixture must still SIGKILL its process group, and post-kill direct-shell reaping
is itself bounded to eight seconds so watchdog cleanup cannot wait indefinitely.
Reap that direct shell with a bounded wait before depending on stdout/stderr EOF:
a descendant blocked in uninterruptible filesystem I/O may retain inherited
pipes after SIGKILL is pending, and pipe drainage must not turn a reaped shell
into an apparent reap timeout. A synthetic test seam must keep a descendant pipe
open while the direct shell is killed and prove that the shell is still reaped
within the bound; the seam must clean its synthetic descendant afterward.
Compressed SIGKILL recovery must carry its codec attribution into replay so
the recovery invocation receives the same finite compressed-DKMS budget.
Short-deadline SIGKILL recovery, failed transaction exits, mixed compressed-
image refusal, DKMS registration ownership and quarantine remain required.
An unhandled fixture timeout must use an allowlisted codec classification and
identify operation, elapsed and budgeted seconds, budget reason, final process
disposition, original shell exit status if already known, and the fixture phase.
A shell that has already exited while descendants hold output pipes must retain
its original exit status and report pipe drainage, not watchdog expiry, as the
first cause. The still-running-shell case must retain watchdog-first attribution.
Both cases must mark recovery journal disposition as not assessed: bounded group
termination and direct-shell reaping do not prove rollback safety. All timeout
diagnostics must avoid private sandbox paths. This synthetic timing witness does
not replace a real F2FS durability trace or change production script behavior.

The systemd/package GitHub Actions gate is rootless exact-source evidence, not a
privileged deployment gate. Its workflow-level concurrency group must contain
`${{ github.run_id }}` as well as the workflow-specific ref prefix:
GitHub's default one-pending-run group replaces an older pending member even
when `cancel-in-progress: false`. Ref-only or SHA-only groups therefore lose
independently useful runs, including multiple dispatches of one SHA. Every job
must explicitly check out `${{ github.sha }}` and identify that SHA in its
run and job labels. The one hosted-runner job must retain shell syntax checks,
the complete hermetic package suite, systemd runtime-health regressions, the
rootless workflow-contract fixture, and patch hygiene without sudo, loading
modules, enabling services, or touching swap. Retain verbose failure steps in
GitHub Actions logs; diagnostics may contain the public run ID and commit SHA,
but must not disclose tokens or private sandbox paths.

Treat three outcomes separately: an executed check failure has a runner log
and a source-bound error annotation; a cancelled run is not a passing or
failing test; and a queued run with no assigned runner has not executed any
test. Runner-capacity or scheduling delay is not a source regression and cannot
reliably emit job-side diagnostics before runner allocation. Never interpret
absence of a runner log as a PASS or misclassify scheduling as a test failure.


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
aliases; admit only a provably distinct stable identity. Also exercise an
unconfigured primary selector plus a syntactically valid, active block-swap
entry with an unresolvable device identity; the hibernation guard must refuse
rather than infer that the unknown swap device is unrelated. Include a
resolved Device Mapper alias with an unreadable or missing sysfs `dm/name`;
major:minor alone must not be treated as proof of unrelated identity. Missing
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

Loaded lifecycle summary counts must be emitted from the validated parsed evidence rather than duplicated numeric constants; when the negative-recovery matrix grows, the parser must validate the new count and report that parsed count so report regressions cannot silently lag the qualification contract.

Lifecycle release-report parsing must derive or explicitly synchronize displayed
negative-case totals with the qualification marker contract. When the null-block
negative-recovery suite grows, update parser counters and rendered-report
assertions in the same change so a green qualifier cannot be hidden by stale
summary metadata.

Exact-source production-C evidence requires the production-C workflow to run on every `main` push. Path-filtered production-C triggers are prohibited because a documentation-only or evidence-contract commit would otherwise make the current Git SHA permanently ineligible for the exact-source required-CI gate.

Package admission must verify the commands required by the installed
runtime-health observer before mutating package state. In particular, the
direct installer must reject hosts missing the bounded-execution utility,
device-mapper/util-linux identity tools, journal reader, or basic text/path
utilities used by the root helper. The hermetic package suite must retain a
source-contract assertion for that runtime dependency set.

Incremental `make test` fixtures that exercise the real `tests/suites/Makefile` must stage every native probe source that Makefile consumes, including both direct-write and direct-read probes, and must track those outputs when asserting that unrelated CLI or authority-header edits do not spuriously rebuild native probes.

Synthetic retained READ-fault evidence must include the exact `syscall_errno:EIO`, zero lower-read delta, and zero submitted-I/O delta in both isolated fixtures and report-parser regressions. Mutation tests must alter fields that are actually present in the canonical marker so a no-op string replacement cannot masquerade as negative coverage.

Persistent real-swap release evidence must prove that the private physical execution-control binary is cryptographically distinct from the installed production `swapzctl`, and that the installed production control reports privileged lifecycle execution locked off. A private qualifier may enable its own sealed execution path; that seam must never make the installed formatter/control executable privileged.

Every loaded shell helper in the official rootless syntax list must remain `bash -n` clean. When a `[[ ... ]]` binary comparison is split across physical lines, use an explicit shell line continuation before the newline so syntax validation and runtime parsing agree; never silence the syntax gate.

The isolated `make test` loaded-evidence fixture and report-contract assertions must emit and expect the same complete primary interruption-recovery matrix required by the parser and owned-nullblk qualifier. When that matrix grows, its `PASS_LOADED_PRIMARY_NULLBLK_INTERRUPTION_RECOVERY=cases:<n>` count, phase set, parsed summary count, and report regression must be updated together; a stale smaller fixture or stale assertion must fail qualification rather than silently reducing or misreporting coverage.

## Private kernel-native diagnostics and static analysis lane

A separate, optional `tests/tools/kernel-debug-qualify.py` lane and rootless
`tests/runtime/native/kernel-debug-qualification-test.py` fixture remain
outside the official `make test` reporter pending runner-owner coordination.
The dedicated workflow runs the rootless negative controls and a compile-only
kernel static-analysis contract; it never installs or boots a debug kernel,
inserts a module, provisions `null_blk`, or substitutes native sanitizers for
kernel instrumentation. Changes to the wrapper, its owned-null_blk
helper/oracle/identity dependencies, the root Makefile/signing hook, or kernel
source all trigger this workflow so the private lane cannot silently drift.
Expected negative-control diagnostics are captured inside the fixture; a
successful rootless contract job must not emit a synthetic FAIL marker.

Static analysis uses the current HWE kernel headers required by the module and
builds the pinned Debian Sparse 0.6.5~rc1 source archive only under
`build/tests`; distro Sparse 0.6.4 is rejected by newer Kbuild before CHECK
because it lacks the required `typeof_unqual` support. At minimum
`dm-target.c`, `codec.c`, `authority.c`, `engine.c`, and
`predictor.c` must have observed CHECK records. Source-located Sparse/Smatch
warnings and errors are classified and fail the static gate; compiler/pahole
compatibility banners without a source location are not findings. Smatch is
used only when already installed and otherwise reports UNAVAILABLE. Sparse
0.6.5~rc1 does not model GCC's vector `__builtin_shuffle` or several GNU
vector brace initializers used by the production SIMD backends. Narrow
`__CHECKER__`-only type/data-flow stand-ins cover only those parser
limitations; ordinary GCC/Clang builds retain the exact production builtins and
initializers, whose byte semantics remain covered by native predictor tests.
The rootless source contract requires both the checker seam and the production
expressions to remain present. The static gate derives the complete expected
translation-unit set from the selected Kbuild configuration: x86_64 requires
the five core units plus SSE2/AVX2/AVX-512, while ARM64 with kernel-mode NEON
also requires its NEON unit. An unreadable Kbuild configuration, any missing
architecture-selected CHECK unit, or any other source-located Sparse finding
fails the gate. Missing headers/analyzer execution or nonzero Kbuild exits must
never produce static PASS.

The read-only host Kconfig probe distinguishes DETECTED, UNAVAILABLE,
DISABLED_AT_BOOT, and UNKNOWN from executed qualification. KASAN+lockdep
requires `CONFIG_KASAN`, `CONFIG_PROVE_LOCKING`, `CONFIG_LOCKDEP`, and
`CONFIG_DEBUG_LOCK_ALLOC`; KCSAN is a separate lane requiring
`CONFIG_KCSAN`. `kasan=off` blocks KASAN. Kconfig detection alone is never
runtime evidence: immediately before module insertion and again after the
owned-I/O session, a privileged read-only runtime snapshot must observe
`enabled: 1` plus the default empty blacklist report filter from
`/sys/kernel/debug/kcsan` for KCSAN, and both
`debug_locks: 1` in `/proc/lockdep_stats` plus
`/proc/sys/kernel/prove_locking == 1` for lockdep. Missing/unreadable runtime
interfaces or an inactive required feature before I/O block the lane; a
required feature that becomes inactive during I/O is a qualification FAIL.
This prevents a compiled-but-disabled KCSAN kernel or lockdep that already
turned itself off after a locking defect from yielding a false PASS.

The private opt-in wrapper
`tests/tools/qualify-kernel-debug-owned.sh` requires a clean `main`
checkout at the explicit validated source SHA, an explicit Codex coordination
token, noninteractive privilege, and no pre-existing `dm_swapz` module. It
runs the rootless contract first, then performs a noninteractive ordinary
project build and requires the module's embedded
`swapz_build_source_sha`/`swapz_build_source_clean` metadata to match the
validated clean source before any load. The built module must also expose
undefined KASAN/HWASAN or KCSAN/TSAN instrumentation references appropriate to
the selected lane, preventing a debug-kernel config from qualifying an
uninstrumented external module. It delegates device work only to the
existing bounded `deploy-nullblk.sh` helper: a fresh identity-verified
RAM-backed `null_blk` lower with configured completion delay, eight
deterministic constructor-stage synthetic `-ENOMEM` failures,
read/write/codec fault paths, byte-exact GC and DISCARD, flush/barrier
coverage, suspend/drain, completion-handoff accounting, and normal teardown.
It never selects physical swap, enables global kernel fault injection, or
force-removes a mapper. Any quarantine remains authoritative.

The wrapper emits `LOADED_HOST_CHECKLIST` before host preflight. The
future owner-host handoff must record the exact running kernel release and
matching Kconfig, module SHA-256 and matching vermagic, clean embedded source
SHA, unchanged boot ID across the pre/post runtime snapshots, and active
KASAN+lockdep or separately active KCSAN instrumentation. Evidence includes
exactly one each of `SOURCE_HEAD`, `RUNNING_KERNEL`, `MODULE_SHA256`,
all ten `PASS_LOADED_*` / `PASS_RETAINED_*` run records enumerated by the
private verifier, and the clean-teardown `PASS:` record. Baseline and final
dmesg must be complete newline-terminated reads from the same boot, with the
baseline an exact prefix of final, bracketing only the owned helper's bounded
900s execution plus 5s termination grace. Reject disabled runtime checkers
before helper admission using the read-only `snapshot-check` gate; a
checker that disables during I/O remains an independent FAIL.

The fixture uses inert temporary PATH mocks and a one-second timeout only
under the private `ROOTLESS_VALIDATOR_ONLY` replay guard. It covers Kconfig
gaps, KCSAN unavailable/inactive, KASAN and lockdep diagnostics, source/build
provenance mismatch, boot-ID change, lost diagnostic prefix, missing markers,
helper exit/timeout/signal and a clean synthetic observation. Each case checks
exit status, bounded messages, child reaping and temporary evidence cleanup.
No replay output can be accepted as `LOADED_KERNEL_PASS`; successful
synthetic evidence is `ROOTLESS_VALIDATOR_ONLY=PASS` only.
The evidence verifier rejects incomplete or reordered KASAN/lockdep selections:
only the full `kasan,lockdep` lane or separate `kcsan` lane can qualify,
even when all synthetic loaded markers and module hashes otherwise match.
It also requires exactly one execution `BOOT_ID=<uuid>` marker matching the
same current boot as both runtime snapshots; missing, duplicated, malformed or
different-boot execution identity blocks qualification with the expected boot
identity and a safe observed category. The production `deploy-nullblk.sh`
producer reads the kernel's real `/proc/sys/kernel/random/boot_id` as one
bounded, newline-terminated lowercase UUID before device provisioning, but
publishes the marker only in its successful, non-quarantined EXIT cleanup,
after re-reading and matching the same boot identity. A short, missing,
malformed, duplicated/extended or changed identity never publishes the marker;
interruption, failed loaded work or uncertain teardown withholds it as well.
Every withheld publication reports a fixed producer phase, expected marker,
safe observed category and retained-evidence status without echoing private
paths or arbitrary input. The helper's session-log fanout is part of that
publication boundary: it preserves the caller output descriptor, closes its
tee input after nonterminal diagnostics, and synchronously joins the owned tee
before committing terminal evidence. Only after that drain succeeds may the
producer append the terminal `BOOT_ID`/clean-PASS pair to retained evidence
and expose the same pair to the caller, so the wrapper cannot read a
still-incomplete execution log and a failed retention write cannot leak a
premature success marker. A tee failure reports sanitized
`phase=evidence_flush` with retained state unknown; a terminal retention
write failure reports `phase=evidence_commit` with partial retained evidence.
Failed publication never prints the private session path, while successful runs
retain the existing `EVIDENCE=...` locator after the terminal pair commits.
The rootless verifier requires a newline-complete owned execution log with
exactly one source/kernel/module binding in producer order, exactly one
consistent producer-owned `nullb-swapz-<token>` / `SWAPZ-TEST-<token>`
identity across `OWNED_CONFIG` and `OWNED_RAM_LOWER`, and all required
loaded records in their real execution order. Distinct owned tokens are
combined-run evidence and block qualification without exposing their values.
Known helper/oracle `FAIL` records are failures whether the marker uses a
colon, underscore or whitespace separator; unfamiliar FAILURE/ERROR/ABORTED-like
records remain ambiguous and block rather than being promoted to FAIL.
Only the published terminal
`BOOT_ID` immediately followed by the exact clean-teardown `PASS:` record
may close the run; an optional single `EVIDENCE=.../session.log` locator may
follow it. Reordered or interleaved records, early or duplicated terminal
claims, trailing unknown output, and unrecognized FAILURE/ERROR/ABORTED-like
control markers block qualification with bounded source/module identities,
the evidence field, phase, safe observed category and recapture action.
An execution log's source/hash/boot markers are evidence consistency checks,
not an authentication signature: this verifier cannot prove that a malicious
actor did not splice same-boot records with identical artifact digests.
Only the actual owned-helper execution and separately retained owner evidence
can establish loaded qualification.

Kernel-debug negative controls must isolate one verifier gate at a time rather
than accidentally tripping a stricter earlier requirement. A duplicate marker
fixture inserts the duplicate adjacent to its canonical record while preserving
the producer's terminal newline. A terminal-tail fixture appends a neutral
nonfailure sentinel so teardown failure parsing cannot win first. Verify-CLI
fixtures write the canonical execution bytes exactly and must not add an extra
blank terminal record. Targeted regressions assert the intended evidence field
and phase and reject the accidental earlier-gate diagnostic; the unchanged
synthetic control must continue to PASS. When real subprocess evidence carries
an exit status or errno, preserve that original numeric value in the sanitized
diagnostic; a validation-only fixture with no producer exit or errno must not
invent one. Never relax fail-closed verifier precedence to accommodate a
multiply-invalid fixture.
Interruption before the initial boot-ID read completes remains
`phase=session_capture`, not an owned-I/O phase. Rootless fixtures execute the
real producer reader and cleanup with synthetic boot files, deliberately
delayed/failing evidence fanout and inert host commands, and may inject this
marker only into synthetic replay evidence; they must still report
`ROOTLESS_VALIDATOR_ONLY=PASS`, never a loaded PASS.
The read-only feature probe can still report individual capabilities.
Kernel diagnostics, helper failure reasons and contradictory source/module/
kernel markers use fixed safe categories rather than echoing private dmesg
records, arbitrary marker values or privileged evidence paths. Runtime JSON
(including the `snapshot-check` CLI input), kernel command line, kernel
configuration, bounded session logs and execution records have finite parser
limits; oversized evidence cannot produce PASS. The private rootless wrapper replay must assert the redacted lockdep
category rather than matching raw diagnostic text. A clean synthetic
verifier result remains rootless-only, not proof of loaded instrumentation.
The replay guard
still rejects EUID 0; replay variables never bypass the wrapper's unprivileged
process requirement. Module source/clean metadata and sanitizer-symbol query
failures preserve the original command exit status without echoing module
paths. This fixture does not boot a kernel, load swapz or test actual
KASAN/KCSAN/lockdep execution.

Runtime verification binds the helper's exact `SOURCE_HEAD` marker to the
validated SHA, requires each selected loaded PASS marker exactly once, requires
the clean-teardown record, requires active pre/post runtime snapshots, and
compares readable pre/post kernel ring buffers with an unchanged baseline
prefix. Any kernel BUG/Oops, KASAN/KCSAN report, lockdep report, kernel
warning, refcount diagnostic, workqueue-after-free indication, shortened log,
missing/repeated
marker, helper failure, or uncertain teardown fails or blocks the lane.
Executed defects return FAIL rather than being relabeled BLOCKED merely because
the wrapper is private. Failure evidence is monotonic: a post-run runtime-state
observation gap may block an otherwise clean result but must not downgrade an
already captured kernel diagnostic or helper defect from FAIL to BLOCKED.

This lane still does not establish every requested kernel-debug claim.
Full simultaneous READ/WRITE/DISCARD/FUA while GC is active, actual bounded
allocator-failure injection beyond the eight synthetic constructor checkpoints,
and execution on suitable KASAN+lockdep and KCSAN owner kernels remain open
until separately run and recorded. Native ASan/UBSan/TSan, source contracts,
Kconfig detection, and Sparse/Smatch compile checks are never KASAN/KCSAN
runtime evidence.

### Physical evidence analyzer integrity (rootless contract)

Physical campaign snapshots include CLOCK_MONOTONIC capture nanoseconds
from the clock shared by the arms. A PASS requires strict same-boot
before/after coverage, globally nonoverlapping arm windows, ascending pair
indices within each cohort, distinct physical run identifiers, exact source,
module and parent-device bindings, immutable fixture hashes, and complete
unscreened attempts. Physical run identifiers are unique across the complete
campaign, not merely within one workload; cross-cohort reuse is stale/duplicate
evidence and invalidates every pair sharing that identity. Each paired raw/swapz
attempt must carry one matching, nonempty physical `workload_id`; a cross-arm
mismatch is BLOCKED rather than eligible evidence. Synthetic file replay and
stale/cached samples are not physical measurements. Diskstats index 8 is an in-flight gauge; every other
cumulative counter must not reverse, and 512-byte sector multiplication is
checked against unsigned 64-bit bytes. The evaluator remains authoritative
for useful read/write I/O, READ p95/p99 histogram tails, CPU per useful
byte, swapz-only observed GC wall time, 3600-second duration, 90% occupancy
and paired t-95% intervals. Raw sustained evidence has no Device Mapper target
status and therefore must keep `target_status_before`, `target_status_after`
and `gc` absent; supplemental diagnostics must not require swapz GC fields
from the raw arm. The sealer's public failure diagnostics cap at 96
bounded numeric observations and include frozen bound, metric, workload,
pair index and arm without copying private representative payload hashes.
Lower-device bytes/requests are host-visible I/O, **not NAND wear**.
Sealer provenance comparisons are type-exact at every JSON depth: a boolean
cannot substitute for an integer arm counter or frozen numeric limit, even
when Python would compare their values equal. The public diagnostic limit
must retain at least one field-level reason for every encountered FAIL,
BLOCKED and UNAVAILABLE classification; displaced
entries remain counted without publishing private samples. An authenticated FAIL dominates BLOCKED, which dominates UNAVAILABLE, so a
later unrelated prerequisite or observation gap cannot relabel already failed
evidence. Identity ambiguity, duplicate IDs or overlapping chronology discovered
while authenticating that witness are part of the witness itself and therefore
keep it BLOCKED. Rootless diagnostic-cap regressions must keep an authenticated
producer failure on a distinct identity-clean pair when proving FAIL precedence;
a late duplicate invalidating that same pair must remain BLOCKED regardless of
which diagnostics fit under the cap. Synthetic capacity/RAM fixtures must
compute the producer's complete host-stability check vector from their
before/after snapshots, never mock a one-check STABLE declaration. The positive
stable-host fixture must itself satisfy the producer's host-snapshot validator;
tests must not patch that validator out merely to obtain a STABLE vector, because
equal missing before/after fields can otherwise pass pairwise stability through
`None == None`. The release validator must reject omitted, false or
type-coerced host checks, and must rederive within/over-limit RAM from sealed
trace evidence rather than a contradictory release-receipt scalar. None of these synthetic controls establish
loaded-host acceptance.
For an explicitly v2 campaign, the physical sealer audit independently checks
every frozen-parent and prospective-amendment workload, including decisions
omitted by the supplied summary. Missing decisions or short attempted/accepted
cohorts are BLOCKED prerequisites, never automatically producer-proven FAIL.
An excluded or evaluator-unusable pair is incomplete evidence and remains
BLOCKED unless an independent producer or measured check proves failure. A
reported measured cohort FAIL must be rederived exactly from the retained
accepted records with type-strict JSON equality; a detached synthetic CI/check
object is BLOCKED rather than measurement evidence. An
authenticated terminal measurement-phase arm producer verdict of FAIL and a
failed measured decision remain FAIL even when another cohort is missing. Raw-repeat spread beyond the frozen
screening maximum remains BLOCKED/INCOMPLETE rather than becoming a
producer-proven failure. The bounded audit retains the
original qualification status and numeric expected/observed pair counts; its
failure-only fields retain the first producer-proven/derived failed audit phase
and safe producer status. BLOCKED/UNAVAILABLE evidence must not manufacture a
failed phase or producer-failure status. Arbitrary producer strings, artifact
fingerprints and host paths must never enter public diagnostics. The two separate complete cohort
requirements remain 14 designated frozen pairs and 24 current v2 producer
pairs; rootless controls provide no physical acceptance.
No pending prospective-v2 amendment is applied as a retroactive replacement.

The physical producer audit must also type-check every nested pair workload
before dictionary membership. Wrong-type JSON workload identifiers and
wrong-type supplied raw-repeat-spread mappings are BLOCKED diagnostics, not
unhandled TypeError/AttributeError exceptions; the historical missing/null
optional raw-repeat-spread map remains equivalent to an empty mapping.
Nested decision proof is equally untrusted: a non-object `checks` value, a
supplied non-list anonymous pair result set, a non-object anonymous result row,
or a supplied non-object anonymous ratio map must emit a bounded field/type
diagnostic rather than throwing. Missing/null optional decision detail retains
the historical isolated-audit empty-collection meaning; it never supplies
physical proof. An authenticated measurement-phase producer FAIL in a different
pair must remain FAIL. The sealer must reject
missing, non-string or unhashable summary/pair identity components before
using them as dictionary keys, with the failing field, expected and observed
types, no private values, and safe recapture/reseal guidance. Rootless
negative controls must test both malformed-only BLOCKED evidence and retained
independent authenticated FAIL; these controls do not qualify a device.

### Malformed sealed-campaign nested evidence (rootless evaluator contract)

An evaluator must treat each JSON-compatible nested campaign object as
untrusted, including retained pair workload identifiers and physical audit
failure witnesses. An invalid workload list, dictionary, null, boolean, or
unknown string is incomplete/contradictory evidence and must return a
controlled release BLOCKED verdict rather than raising a Python TypeError.
Validate the string type before dictionary membership or set-key operations;
preserve the frozen-parent and complete v2 cohort checks. The producer audit
count invariant is `0 <= accepted_pairs <= retained PASS/non-excluded pairs
<= attempted_pairs`; analysis screening can reduce accepted counts without
rewriting immutable pair artifacts. Never require strict accepted/PASS equality.

Malformed nested-field failures must produce bounded, redacted diagnostics
stating a phase, failed evidence field, expected/observed types, original error
if available (otherwise `unavailable`), verdict, and safe recapture/reseal
action, without echoing private pair records or host paths. This applies to
wrong-type values and structurally invalid values of the nominal type, such as
an unknown workload string or incomplete count map. Preserve earlier
failed-phase attribution if multiple gates fail. A malformed field in the
first-failure witness cannot authenticate its own FAIL. Once the witness,
source/target identity, retained pair manifest and that witness workload's
count invariant are independently authenticated, malformed count or diagnostic
records belonging only to another cohort still block audit completeness but
must not relabel the authenticated producer/measurement FAIL as BLOCKED. A
passing rootless test only proves the evaluator behavior: BLOCKED is not an
acceptance PASS, and authenticated measured FAIL is neither BLOCKED nor a
qualification PASS.

Release-evaluator truncation regressions must retain the first authenticated
FAIL when the matching diagnostic, pair disposition, source/target identity
and failing-cohort counts remain available, even if unrelated diagnostics were
omitted. Removing that matching diagnostic leaves a first-failure claim
unverifiable and yields BLOCKED; omitted diagnostics also prevent audit PASS.
Malformed count values (including boolean values presented as integers),
inflated accepted-pair counts, stale source/target bindings, and absent
current evaluator/sealer SHA-256 proofs cannot authenticate FAIL. The sealed
qualification target binding must retain the current sealer's complete physical
and parent identity (PARTUUID, size, lower and parent major:minor, parent model
and transport); omitting parent fields is unverifiable rather than a weaker
identity schema. The lower-device and parent major:minor values must be
distinct: equality is a contradictory self-parent topology and is BLOCKED for
both PASS claims and purported authenticated physical FAIL. The release evaluator must reject floating-point or boolean
physical byte sizes and missing nested target/physical-parent fields even
when a campaign self-declares PASS. Its refusal retains
`first_failed_phase=qualification_target_binding`, the expected schema class
`current_physical_target_parent_exact` and observed schema class
`invalid_incomplete_or_mismatched`; contradictory parent observations never
qualify release. For invalid campaigns, the release blocker reports source
identity with `expected_source_identity_class=release_source` and a bounded
observed class (`match`, `mismatch`, or `invalid`) rather than raw source
SHA values, while preserving the original status and authenticated FAIL or
BLOCKED disposition. An authenticated terminal arm FAIL must retain a bounded
producer diagnostic whose expected PASS, producer FAIL status and failure phase
agree with the first-failure witness; a missing or contradictory diagnostic
phase cannot be promoted to measured FAIL. Its public blocker identifies the
producer-failure binding field and expected/observed schema classes, not the
private producer error text. Wrong-typed or null diagnostic collections are
controlled BLOCKED evidence and must not raise while checking that binding.
Report the
invalid field and expected/observed types with bounded, redacted recapture
guidance. Regression fixtures must locate an authenticating diagnostic by the
failure-witness identity rather than retained-list position, and type-strict
count controls cover `required_pairs`, `attempted_pairs` and
`accepted_pairs`. Valid-type count contradictions must identify the exact
audit count field, its producer-policy, retained-manifest or analyzer-usable
count class, expected count/range, observed count, unauthenticated-proof reason,
and safe recapture/reseal action without disclosing private pair content.
Public release blockers report only source/target/artifact binding classes:
they must not print source SHA values, a physical PARTUUID, pair content, host
path, or sealed
artifact SHA-256 fingerprint. The earlier failed-phase attribution still takes
precedence. An authenticated measurement FAIL remains FAIL when an unrelated
cohort is missing records; completeness still blocks release readiness.
Owner, real-swap and cold-boot release refusals must likewise report the
failing source, tested-commit, qualified-artifact, target or mapper-identity
gate by bounded match/mismatch/invalid binding classes. They must not echo
required or forged source SHAs, module or evidence digests, target PARTUUIDs,
host identifiers or attacker-controlled mapper names. Nested metadata-RAM
validation may retain safe numeric and boolean detail, but source SHA, host
boot-ID and mapper-UUID differences must be translated to binding classes
before the validator error reaches a public release blocker. Rootless synthetic
regressions must include mismatched valid identities, wrong signed artifact
digests, malformed or overflowing counts, and both PASS- and FAIL-claimed
boot evidence. An invalid class is not permission to authenticate a producer
FAIL or promote a stale PASS; preserve the original failure phase and the
frozen source/target/workload/pair/measurement requirements.
These are rootless verdict-logic controls only, never physical acceptance
evidence.
