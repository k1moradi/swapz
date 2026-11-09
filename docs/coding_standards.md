# Coding Standards

**Immutable naming policy (read before every prompt):** The project is `swapz`; the kernel module is `dm-swapz.ko` (loaded as `dm_swapz`); the Device Mapper target is exactly `swapz`; and the module alias is `dm-swapz`. Never put implementation-generation numbers in product, module, target, source-path, report, workflow, helper, or schema names. `SWAPSPACE2` is the only physical backing partition format. `SWZ` denotes the existing internal extent-packing design and a legacy in-band codec awaiting RAM-only metadata migration; it is **not** a partition format or permission to persist swapz metadata. Do not invent a new format identity.

**Three-tier test policy:** `make fast_test` is development-only and never qualifies or publishes `test_results.json`; `make test` runs the algorithm/RAM path and returns INCOMPLETE (nonzero) until physical source/run/target admission is qualified; `make test_full` retains all rootless DKMS/systemd integration and RAM qualification. Both privileged tiers report BLOCKED (nonzero) if noninteractive privilege is unavailable. RAM/integration PASS cannot certify physical storage or cold-boot production acceptance. Private scripts and CI jobs are implementation details, not operator interfaces.

The qualification reporter must distinguish the algorithm/RAM and full
integration tiers in its evidence. No RAM result becomes a physical/production
PASS until the protected source/run/target admission protocol is qualified.

## Mandatory ordinary Linux swap partition design (2026-11-09)

Real backing must be an existing, valid SWAPSPACE2 Linux swap partition.
Never repartition, run mkswap on, or rewrite its header, UUID or partition
table. After a safe swapoff and exact-exclusive admission, only the data
area after the protected 4096-byte first page may be used. The newly
created virtual Device Mapper mapper alone may receive mkswap.
Device Mapper iterate_devices must describe only the allocated lower data
range: start at the reserved-page offset and report exactly the aligned
physical-block count, excluding the header and unused device tail. A
header-free null_blk still starts at zero.
Switch between ordinary swap and swapz with verified swapoff/swapon,
without reboot. After a successful trial, obtain the owner's choice:
keep swapz active or return to ordinary Linux swap.

All swapz-specific record and extent descriptors, offsets, lengths,
generations, CRCs, mapping/segment allocation and GC metadata must
be bounded volatile RAM state. RAM descriptor/transaction storage must be
disjoint from the exact lower-write image and the builder itself; builders
reject overlap before reading payload bytes or mutating either ownership
domain. Appends reject payload sources overlapping either writable buffer.
Production writers that have already proved per-extent logical-page uniqueness
must use the descriptor-array-free RAM builder mode and bind each transient
last descriptor immediately into preallocated staged transaction RAM; do not
add large per-write kernel stack arrays or heap allocations. Thus a data-only
backing image contains payload bytes and deterministic zero padding only. The current compressed codec still stores
extent header/descriptors on backing media, and synthetic null_blk
rehearsals still use SWAPZ001. Both are nonconforming migration debt,
not accepted partition-format designs. Preserve 4/8/16KiB packing,
readback integrity, ordering, concurrency and fail-closed semantics.
Production acceptance remains blocked until migration and tests pass.

Earlier permissions to format/repartition even the dedicated SD card
are superseded; only post-swapoff swap *data* may be overwritten.

## Priority

More than half of ongoing development engineering time should concern production Linux kernel C: debugging, profiling, algorithms, I/O ownership, mapping authority, GC and measured performance. Do not invent tests or infrastructure when a direct C fix is the work that matters. Python and shell are thin qualification glue.

## Source and naming

Active product C/C++ and headers live under `src/`; test-only code lives under `tests/`; maintained project documentation lives under `docs/`; packaging code lives under `packaging/`. The sole root-level Markdown exception is `AGENTS.md`, which is repository-control metadata intentionally rooted for coding-agent discovery and is not product documentation. Do not create any other root Markdown or recreate parallel `kernel/`, `userspace/`, `tools/`, legacy source trees, alternate research modules or historical models.

Use `swapz_` / `SWAPZ_` for implementation identifiers and `swapz` for the product/candidate. The Device Mapper target is exactly `swapz`; the module alias is `dm-swapz`. SWZ may name the internal packing and legacy codec only. The real backing partition remains SWAPSPACE2; no on-disk swapz metadata is permitted in the completed design.

Build provenance must expose a single source SHA and a clean/dirty value to
userspace and the kernel module. Generate the string form consumed by
`MODULE_INFO()` alongside the numeric form; the checked-in fallback header must
remain guarded against duplicate definitions when a generated header supplies
both. The Make-interface regression must inspect the generated value, not only
the fallback header.

### swapzctl status compression accounting

`swapzctl status` is a read-only Device Mapper observer. It may enumerate
active mappings and request the target's information status, but it must never
create, suspend, resume, remove or otherwise mutate a mapper, backing device or
swap state. Compression accounting is cumulative for successful foreground
writes since target creation; it is not current live-map occupancy, physical
NAND wear or a replacement for the qualification report.

The compressed-SWZ ratio uses `compressed * 4096` logical bytes divided by
successful foreground lower-WRITE bytes attributable to compressed SWZ extents.
Foreground bytes are `physical_write - gc_write`; subtract exactly one 4KiB
block for each committed RAW page. This denominator intentionally includes SWZ
headers, extent rounding and packing cost. The INFO `bulk_padding` field is a
saturating unsigned-32 count of 4KiB padding blocks **staged** by the serialized
write engine, including stages later aborted or failed; it is not committed
foreground/GC accounting. Zero means no padding was ever staged, never a
wrapped counter. UINT32_MAX is saturation, not an exact lifetime block total.
For bulk mode 2, any nonzero `bulk_padding` therefore requires the
compressed-only ratio to be UNAVAILABLE because committed compressed extent
bytes cannot be separated from possible padding. This may be conservative
after an aborted stage. The existing INFO field and overall committed ratio
remain unchanged; do not subtract staged padding or estimate it.

The overall ratio uses `logical_write / (physical_write - gc_write)`. RAW
pages therefore contribute 4KiB logical and 4KiB lower bytes, while zero-elided
writes contribute 4KiB logical and no lower data bytes. Report GC lower-WRITE
bytes separately and exclude them from both representation ratios. Never derive
a committed ratio from `lz4_accepted_bytes`, size bins, predictor results or
other attempt-side diagnostics.

Status parsing must use exact `key=value` tokens, checked arithmetic and
bounded Device Mapper buffers. Before printing ratios, require two consecutive
snapshots with identical relevant monotonic counters and validate
`logical_write == (compressed + raw + zero_elided) * 4096`. A malformed,
overflowing, unstable or failed target must not produce a numeric ratio.

Device Mapper `DM_TABLE_STATUS` and `DM_LIST_DEVICES` wire records use an
explicit eight-byte alignment independent of C struct `_Alignof` (including
32-bit hosts). Validate absolute target offsets, aligned terminal offset,
bounded counts, NUL containment and all target records with checked byte
offsets and copied headers; do not dereference unaligned wire structures.
Bind each LIST_DEVICES name to its device number on both INFO observations,
compare the complete ordered target inventory, event generation, geometry,
status and all committed ratio counters across two full reads, and withhold
all numeric status output until every enumerated device validates. Distinguish
BLOCKED, FAILED and UNAVAILABLE with device/index/generation/field or errno
without echoing untrusted INFO text. Observational ioctl permission denial
may require CAP_SYS_ADMIN and must never trigger privileged escalation.
Reset per-read diagnostic state before observing the next generation so a
second-read ioctl errno cannot inherit a prior target parser failure. Apply
LIST event-generation binding only after a successful INFO parse; a failed or
unavailable INFO observation is not a valid generation sample and its original
BLOCKED, FAILED or UNAVAILABLE diagnosis must not be overwritten by EAGAIN.
A tableless mapping legitimately reports target_count=0 while DM_TABLE_STATUS
may leave data_size at the caller's request capacity; treat that as an empty
target inventory and never parse request-buffer slack as returned records.
For each LIST_DEVICES record, require the NUL-terminated name plus its
8-byte-aligned event-number/flags trailer to fit inside the record, and bind
that enumerated event generation to both status observations. A generation
change after enumeration is UNAVAILABLE, not permission to report a newer
table under an older list identity. Even unchanged listed mappings do not
prove a complete inventory: another mapping may be added, removed, renamed
or reordered while the two per-mapping INFO reads succeed. After staging all
status results, perform a final read-only DM_LIST_DEVICES and compare the
complete ordered mapping names, device numbers, event generations, flags and
bounded UUIDs (when present) against the initial list, before emitting any
numeric results. Production LIST_DEVICES requests must set `DM_UUID_FLAG` so
the kernel returns UUID metadata where supported; a synthetic reply containing
UUIDs is not sufficient evidence if the real ioctl never requests them. A
changed, malformed, oversized or unreadable final list
withholds every staged metric and reports a bounded BLOCKED or UNAVAILABLE
diagnostic. This is drift detection between observations, **not** an atomic
kernel-wide snapshot: changes after the final ioctl or changes that occur and
reverse between observations cannot be ruled out. For nonfinal DM_TABLE_STATUS records,
require spec.next to equal the exact 8-byte alignment immediately after the
status NUL; aligned gaps are malformed rather than ignorable padding.

Kernel information-status emission may use multiple bounded `DMEMIT` calls to
keep callback stack use bounded. The externally concatenated INFO stream is the
contract: preserve token order, names and values across emission chunks.
Source-contract helpers may reconstruct that stream for token-order checks,
while counter-ownership assertions continue to inspect the actual C
expressions. Large diagnostic snapshots may use bounded `GFP_NOIO` scratch
allocation instead of kernel stack; allocation failure must emit an explicit
error status without fabricated counters or backing-device I/O.

### Representative-memory tooling

Representative-memory analysis must be explicitly owner supplied and offline.
Do not harvest from process memory, `/proc`, live swap, physical partitions or
block devices. Stream bounded page records; keep raw samples out of Git and
published reports; emit aggregate statistics only, without page bytes,
per-page records, page hashes or source paths. Keep transient sample buffers
out of swap and core dumps where the platform permits, clear them after use,
and place temporary fixture copies in private directories with restrictive
file modes. Before a Python process opens representative fixture page bytes,
disable core dumps/dumpability and lock current and future mappings; fail closed
if RLIMIT_MEMLOCK or OS support is insufficient. Privileged replay must recheck
the private fixture metadata because sudo may discard environment; the native
replay independently locks its mapped fixture and all future allocations.
Do not keep a global representative-content marker in the parent test runner:
each replay scopes its protection to the fixture and its own process. Privileged
shell helpers must preserve the immutable snapshot boundary with the dedicated
private-memory copier: the unprivileged orchestrator also passes an explicit
private-fixture flag across sudo, so protection does not depend solely on
mutable metadata. The copier protects before reading representative bytes,
rejects symlink/changing sources, never removes a destination it did not create,
writes mode 0600, and fsyncs the snapshot. Generic
cp/dd/cat processes may copy nonsensitive metadata/traces but must never stage
representative page bytes outside the protected readers.
A local ignored benchmark artifact may keep its existing fixture
digest only to prove the raw/target arms shared identical inputs; never publish
that artifact or the sample. This tooling does not qualify kernel swap
semantics or physical storage behavior.

## Kernel C rules

Use Linux-kernel-style C, kernel types/APIs, explicit ownership and checked arithmetic. Keep functions cohesive, allocations bounded, stack use modest and concurrency ownership obvious. Avoid recursion, hidden allocations, libc/C++ in the module and duplicated state machines.

Every accepted BIO must have exactly one completion owner. Never publish a mapping before all required lower data and ordering work succeeds. Preserve generation/CRC checks, PREFLUSH/FUA ordering, same-page dependencies, discard semantics, suspend/drain safety and fail-closed teardown.

Target construction is pre-admission ownership: every failure after acquiring a
backing device, dm-io client, authority arrays, scratch, read slots or workqueue
must converge through the same idempotent teardown path before `accepting` can
become true. The `test_fail_constructor_stage` module parameter is a
qualification-only seam: zero by default, read-only after module load, restricted
to positively identified `null_blk`, and rejected for physical backing. Its
staged `-ENOMEM` failures must never issue lower I/O or leave a mapper, backing
holder, workqueue, dm-io client or module reference behind. A read-only atomic
hit counter must advance exactly once for the configured stage so an unrelated
table-load failure cannot masquerade as constructor-failure evidence. Do not use
global kernel allocation fault injection to qualify this ownership contract.

The detached lower-WRITE callback publishes `lower_done` and queues the ordered
owner under the same `queue_lock` gate used by drain. A waiter can advance as
soon as completion is visible; no target or in-flight-slot access may follow
the callback's final unlock. READ callbacks that end with completion publication
must likewise perform all slot accesses before that publication.

Kernel API compatibility must be capability-probed when distributions can
backport an interface independently of `LINUX_VERSION_CODE`. Keep such probes
at the build boundary and route production call sites through one typed wrapper.
For Device Mapper `dm_io`, both ordinary error bits and separate unsupported
bits are failures; asynchronous callback compatibility must not duplicate
completion ownership or publication logic.

A RAW authoritative mapping occupies exactly one 4KiB physical block.
Validate this representation at the range-prevalidation, direct page-DISCARD,
RAW finish and compressed finish boundaries, even when the cached extent
class, start liveness and segment geometry are mutually consistent.
A malformed multi-block RAW source must not release any old reference,
advance a logical generation or expose a new mapping. A failed staged
completion may quarantine its reserved destination, but must preserve
all pre-existing authoritative maps and sidecars. Use deterministic rootless
fault injection to exercise this invariant without lower-device I/O.

Authority proof traversal locals must avoid identifiers that collide with Linux
context macros such as `current` and use descriptive role-bearing names:
`current_logical`, `last_logical` and `visited_pages`. The rootless
source-contract regression must retain that lexical guard in addition to sparse
kernel qualification, because userspace exact-C compilation does not expand the
kernel macro.

For compressed extents published with more than one record, every sibling map
must retain an in-map shared-extent witness. Before direct DISCARD, RAW COW,
compressed COW or GC relocation would reduce that extent's physical reference
count to zero, authority must independently prove that no sibling survives.
Production may use the preallocated per-segment intrusive page list as an
early consistency gate, but that reverse index and its mapped-page count are
cached sidecars, not final ownership authority. A would-be final shared-extent
release must still confirm overlapping references against the complete primary
logical map, even when the reverse-index sidecars are mutually self-consistent.
Multi-page DISCARD instead folds this condition into its single post-model
full-map preflight, before the first generation changes. A stale-low liveness
sidecar, including one paired with a forged-low reverse index, must therefore
fail closed without invalidating a sibling mapping or publishing a replacement.

Range DISCARD must preflight every requested mapping before the first
logical generation or liveness mutation. A valid extent start index alone is
insufficient: the entire 1/2/4-block extent must fit physical capacity and
stay inside its 256-block segment. Zero-overwrite elision must apply the same
mapper-local whole-extent bounds predicate before reading segment sidecars or
invalidating authority. If a later descriptor is corrupt, earlier generations
and live-record counts must remain unchanged. This is a mapper preflight
invariant; advisory lower TRIM must not weaken logical atomicity.

Test-only lower-I/O injection must stay outside physical backing and fail before
submission accounting. WRITE and READ injection are independent constructor
seams; the READ seam is shared by the synchronous engine adapter and both
bounded read-slot adapters, and its call/injection counters are atomic because
those helpers may execute concurrently. An injected READ must not increment
submitted/completed lower-read counters, mutate authority, or be converted to a
successful upper completion. Production Device Mapper tables omit all fault
arguments.

Allocation and GC must never reuse a possibly live or partially written extent. GC may relocate only current authoritative records and must account for its lower READ/WRITE cost. Once a GC rotation owns a destination, the serialized worker must retain an authenticated victim/destination recovery token and the destination's monotonic allocation cursor until that same rotation commits. A later nonempty WRITE or DISCARD may not mutate authority until the owned recovery has resumed or failed closed. Retries rescan current victim membership so already-published generations are never duplicated; a reserve becomes reusable only after authoritative liveness reaches zero. Packed and standalone RAW callers must classify a lower-I/O failure that leaves this authenticated recovery active as retryable for the GC state rather than poisoning the whole target; unrelated RAW/FUA failures and authentication mismatches remain terminal. Every outer WRITE owner that receives that propagated -EIO after an inner GC flush must repeat the same decision before electing target failure: it may keep the error per-BIO only while the token remains active and the target failure flag is still clear; if a terminal error was elected while unwinding, the outer owner must not suppress it. Recovery ownership alone cannot make a corruption error retryable: the shared GC return path permits only the synchronous lower-I/O -EIO and the nonterminal capacity -ENOSPC without target poisoning; integrity (-EBADMSG), authority (-EUCLEAN), unsupported operations and all other unexpected GC errors are terminal before either foreground caller can suppress failure. The worker recovery token also tracks the destination allocation high-water; a lower or backward cursor on resume is an authentication failure, not permission to reuse uncertain blocks. A completely full destination may roll forward only into its authenticated, independently verified-dead former victim; the exceptional worker preflight must scan all authoritative maps and every physical liveness entry, regardless of cached per-segment counts, before any recycle hook or role transition. The original destination remains live until evacuation finishes, and foreground mutations remain fenced throughout. If independent zero-liveness proof fails, keep the owned rotation fail-closed.
A recovery destination can also become unusable before numerical fullness when
a 2/4-block compressed extent cannot fit its remaining segment tail. That
-ENOSPC must not retry the same placement forever. The serialized recovery path
may claim one different independently verified-dead reserve, then and only then
promote the blocked destination to foreground and rebind the exact worker token
to the new destination while retaining the original victim and forbidden OPEN.
This exceptional destination advance consumes one reserve role and is bounded
to one role handoff per worker call. Track initial/current reserve-role counts
in serialized target state rather than rescanning a concurrently changing role
array from status; decrement only after a validated destination advance and keep
ordinary one-for-one rotations unchanged. Target status also exposes a
saturating successful-advance counter. Runtime health warns on any reserve-role
erosion, fails on zero or an impossible current count above the initial count,
and treats missing telemetry as degraded evidence. If no replacement reserve
exists, convert the owned no-progress condition to terminal fail-closed state;
ordinary foreground -ENOSPC outside an owned recovery remains nonterminal.
GC cost-accounting sidecars must preflight u32 live-byte and estimated-I/O
overflow and u16 minimum-live-block overflow before publishing replacement
mappings. Even a completed lower write that fails this accounting check must
abandon its reservation, retain the previous authoritative generation and
payload/CRC, and never reuse the uncertain physical block. Synthetic saturated
counter probes establish only this rejection boundary, not full-card progress.

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
kept only when explicitly labeled as burst/wave evidence. A mixed persistent
lane must own its WRITE pages independently of every other lane and use an
immutable disjoint READ region, unless a stronger cross-lane oracle is proved.
A barrier-isolation experiment must give its wave control the identical trace,
payload stream and final image; changing ownership and barriers together does
not isolate barrier cost.

Development benchmark consumers must honor the `make fast_test` machine-readable
`performance_validity.performance_usable` flag before comparing useful service.
Host-noise screening uses quiet pre/post counter deltas, timed steal and raw
repeat drift; timed CPU utilization/PSI includes product work and is not alone
evidence of external interference. Preserve noisy measurements for diagnosis,
exclude them from performance decisions, and keep missing telemetry unavailable.
The screen is a heuristic and never replaces exact-source owner qualification.

## Dead-code rule

Keep the working tree centered on code that ships or directly qualifies the current product. Historical reproduction belongs in immutable Git history. Delete alternate implementations, obsolete compatibility harnesses, unused models, stale workflow gates and historical test-only backends once no active product invariant depends on them.

Before deleting production code, identify all current callers and preserve necessary behavior in direct production-C tests. Never restore dead product code merely to satisfy an orphaned test; delete or rewrite the stale test when its subject no longer exists.

## Change discipline

Work directly on `main` ONLY. **Creating or using ANY other branch and
creating or using ANY pull request are prohibited**, including temporary/agent
branches, drafts, CI-only PRs, forks and secondary worktrees. No GitHub
`create_branch` or `create_pull_request` actions, `git switch -c`,
`git checkout -b`, or branch-targeted pushes are allowed. Historical remote
branches and PRs are read-only, not permitted alternatives. The mandatory
root [AGENTS.md](../AGENTS.md) and [AGENT_CONTEXT.md](AGENT_CONTEXT.md)
define the complete main-only protocol. If direct-main publication is denied,
preserve unpublished work and report BLOCKED; do not fall back to a PR.

Before editing, fetch and require a clean local main synchronized with
`origin/main` and the canonical remote head. After
each completed commit, push normally and verify local HEAD equals `origin/main`.
After long tests, fetch again before publishing. If the remote advanced while an
unpublished local commit exists, reconcile only that unpublished work onto the
new head without rewriting published history, rerun affected checks, and push
normally. Never force-push or overwrite concurrent work.

Every implementation task updates the relevant governing standard in the same commit. README/VISION change only when user-facing structure or acceptance criteria change.

### Documentation working context

Read [AGENT_CONTEXT.md](AGENT_CONTEXT.md) after every repository sync and after
any documentation change. Keep AGENT_CONTEXT, VISION and README continuously in
agent context; retrieve only relevant sections of ROADMAP, this file,
testing_standards and context. Documentation must stay within 25 percent of a
256K model context (64K tokens), with the always-loaded set normally <=24K.
Compact settled narratives into one active rule/evidence anchor and rely on Git
history for transcripts. Documentation changes are part of the implementation:
if behavior, target scope, acceptance criteria or evidence changes, update the
governing text in the same work cycle.

Files under `docs/handoff/` have two distinct purposes. Temporary work
orders and optimization-round results should be retired once their decisions
and essential invariants are captured in ROADMAP or the governing standards;
repoint stale links and let immutable Git history retain disposable transcripts.
Explicitly labeled historical evidence archives may remain when active documents
link to them to preserve source-bound failures, results, and implementation
chronology verbatim. Those archives never become current operator instructions
or qualification PASS. Machine-read data that code opens (currently
`docs/handoff/host-history.json`) is not a handoff document and moves only
together with its reader.

At the end of every optimization round, refresh the active host's historical
performance plots from committed `test_results.json` reports and display every
generated or refreshed plot inline to the owner. The private
`tests/tools/plot-history.py` helper pools PASS reports with the exact host
identity digest into `build/history/<architecture>-<digest>/`. Its default
ARM64/NEON seven-CPU cohort remains a separate descriptive reference under
`build/history/arm64-neon/`, with its documented identity limitations. The
generic `docs/handoff/host-history.json` registry holds per-computer owner-
confirmed legacy report SHAs and audited host metadata. The plotter also writes
`legacy-candidates.json` for older unidentified PASS reports whose architecture,
online CPU count and executed backend evidence resemble exact-host reports;
matching kernel evidence ranks a candidate higher. Candidates are suggestions
only and never enter a pooled series automatically. A legacy report is included
only after owner confirmation by immutable SHA and the registry's CPU/backend/
five-stage checks; its provenance stays explicit in `history.json`. ISA/CPU
count alone does not establish a host match. Exclude failed/blocked reports and
unqualified fast-test trials. Keep default-LZ4 mixed, optional policies and
sustained WRITE QDs separate.
Use each report's own raw controls and break lines at kernel/model/content/replay
changes. History is descriptive, not causal attribution or physical wear evidence.
If no new owner report exists, state that the plots still end at the prior
qualified source. This closeout creates no new public test command or publication.

Host RAM type/speed, virtualization and CPU/queue service can limit RAM-backed
device emulation. Verify what the host exposes and retain achieved raw controls;
do not infer a RAM bottleneck from low 4KiB throughput alone or claim physical
NVMe fidelity from a configured bandwidth ceiling. Never combine ARM and x86
history or retune only one arm to make a desired model rate appear achievable.

## Host safety

Never intentionally reboot, panic or crash the development PC, force-remove an
active mapping, unload a module with users, or touch an unrelated physical
device. Generic loaded qualification uses positively owned RAM-backed
`null_blk`. The current dedicated-host standing scope in AGENT_CONTEXT also
permits destructive initialization, DISCARD/TRIM, benchmarking, `swapon`,
`swapoff` and repeated live-swap work on the positively identified removable
SD card. Before every destructive phase, reprove the opened partition and parent
identity; a pathname alone is never authority. A failed mapper `swapoff` or
ambiguous ownership/state stops teardown rather than authorizing force.
For RAM-backed null_blk, loaded preflight must share the native strict sysfs
devno/alias parser: either the configfs-derived disk name or the index-derived
disk name may exist, never both, and an alternate disk entry remains ambiguous
even when its dev attribute is absent or dangling. Reject malformed or multiply
reported /proc driver majors, require exactly one block-device section, and
preserve the first parser status in the refusal. Configfs numeric identity
attributes must likewise be bounded,
single-record, newline-terminated canonical unsigned values; command
substitution must not normalize malformed attributes into identity proof.
Index-based ownership must not skip a token-shaped configfs candidate whose
index is missing, unreadable or malformed: inability to prove that candidate
different is ownership ambiguity. Shared identity readers must bound input
before validation rather than reading an arbitrarily large malformed record.
No telemetry, token, or stale mapper snapshot grants creation authority.


### Legacy synthetic formatter descriptor and SWZ header contract (retirement pending)

The old instructions below are only for synthetic fake devices, not physical
partition formatting. Production swapzctl format is forbidden.

The standalone formatter has no implicit authority derived from a pathname,
root privilege, or the project's standing permission for one development card.
There is no destructive `swapzctl format <blockdev>` form. Formatting requires
one complete identity bundle in fixed order:
`--expect-major-minor <major>:<minor> --expect-bytes <decimal-bytes>
--expect-partuuid <partuuid> --expect-parent-major-minor <major>:<minor>
--expect-parent-model <model> --expect-parent-transport usb`.
Integers are canonical unsigned decimal values that must fit the platform
`dev_t`/64-bit geometry, and the PARTUUID is canonical hexadecimal plus
single internal hyphens. Numeric parsing must compare each incoming digit to
the field's limit before computing `limit - digit`, including small sysfs
ranges such as the removable attribute's 0..1 bound. The formatter contains no hard-coded development
device path, major:minor, capacity, PARTUUID or parent identity.

The supplied identity bundle is **not an authorization grant**. Before any
device open, the standalone formatter must read the existing protected
root-owned primary-target selector with the manager's read-only verified
configuration API and require its canonical PARTUUID to match the expected
partition exactly. Missing, changed, malformed or unreadable protected
configuration refuses formatting even for an otherwise matching removable
drive. Recheck that protected selector with every opened-descriptor
revalidation, especially immediately before the header write. The standalone
formatter does not acquire privileged lifecycle authority, perform an implicit
selector update, or authorize a different card merely because its CLI
arguments and sysfs topology agree.

Before opening for mutation, the path and `/dev/disk/by-partuuid/<PARTUUID>`
alias must both resolve to the expected partition device number. The matching
`/sys/dev/block/<major>:<minor>` object must identify a real non-virtual
partition, repeat the same PARTUUID in its uevent, have a distinct physical
whole-device parent, and that parent must be the exact expected device, report
removable media, match the expected printable model, and resolve through a USB
transport path. The selected partition must be the parent's sole partition.
Both the partition and its parent must have empty holders and slaves, and
neither may appear mounted or as active swap. Production formatter clearance
requires a complete well-formed zero-row `/proc/swaps`; every active row,
including an apparently unrelated regular swapfile or block device, refuses
with `EOPNOTSUPP` until a separately reviewed kernel-held backing identity,
lower-device ancestry and exclusion contract is proven through the destructive
write. `/proc/swaps` is an activity inventory, not a transferable userspace
identity handle: `seq_file_path()` renders the retained kernel `struct file`
path, while a later `lstat()` resolves the emitted string through the
formatter's current mount view. A private bind overmount can preserve the
retained `d_path()` string while redirecting that lookup to a different
regular file and filesystem `st_dev`; therefore current `st_dev`/`st_ino`
or block-node `st_rdev` is not production admission authority. Ordinary
rename/unlink is a control rather than the demonstrated gap: `d_path()`
follows the rename and marks an unlinked retained file ` (deleted)`.

The readable `/proc/swaps` inventory must contain the kernel's exact tabbed
five-column header; empty, headerless, malformed or type-inconsistent rows
refuse formatting rather than being interpreted as no active swap.
Kernel-escaped swap paths must decode `\\040`, `\\011`, `\\012` and
`\\134` during inventory validation, while other raw non-NUL filename bytes
remain valid. Every record must terminate in a newline; embedded NULs, records
of 8192 bytes or longer, inventories over 16 MiB or 65536 data rows refuse.
Multiple active rows remain non-clearance; pathname identity deduplication must
not turn any active inventory into permission to format.
Mount inventory must inspect the formatter's own mount table and every
distinct visible mount namespace, not just its own mount namespace. An empty
opened PID mountinfo table is ambiguous and fails closed except for a peer
whose mount-namespace device/inode matches the coordinator: that redundant
view may be skipped only after the coordinator table contains a valid `/`
mountpoint row, `/proc/self/root` resolves exactly to `/`, and a second
namespace identity check still matches. The coordinator's full-root mount
table then covers that shared namespace. A foreign empty table or a chrooted
coordinator never uses this exception.
Top-level `/proc` enumeration exposes thread-group leaders only. Enumerate
each visible `/proc/<pid>/task` directory and inspect every non-leader
`/proc/<pid>/task/<tid>/ns/mnt` plus its task-specific `mountinfo`; mount
namespace membership can differ between threads. Count visible leaders and
non-leader tasks against one finite 4,194,304-entry ceiling, and cap the
combined bytes parsed from all mount tables at 64 MiB. A task namespace may be
skipped only when its identity is revalidated and matches the coordinator's
namespace whose complete root table was already validated. Normal process or
thread exit is not storage ambiguity: an EINVAL, ENOENT or ESRCH failure to
open a PID or task mount table may be ignored only when the corresponding
namespace path is also absent. A still-present namespace, unreadable or
incomplete task directory, any other open failure, or any failure after a
mount table was opened refuses formatting. After reading a task table,
revalidate that its namespace identity did not change. These are repeated
snapshots, not an atomic freeze against new mounts, detached namespace file
descriptors or inaccessible mount namespaces.
Mount inventory parsing
must accept Linux pseudo-filesystem major-zero device identifiers (for example
`0:20`) without mistaking them for the selected nonzero-major block device.
Every opened mount table must contain at least one complete row. Mount IDs
and known numeric propagation IDs are canonical positive signed-int decimal;
the device field is a valid major:minor; the mountpoint is an absolute path
with the kernel's octal escaping; and all three post-separator fields are
required. The root field is filesystem-specific and may be a non-path token
(for example nsfs), so it is required but not assumed absolute. Known optional
propagation tags must validate, while unknown optional fields are ignored as
required by the extensible Linux mountinfo grammar. Known propagation tags may appear at most once and the mount/superblock option
fields must carry the kernel's ro/rw prefix. Duplicate mount IDs within one
table are malformed. The combined process/task scan is finite at Linux's
64-bit PID_MAX_LIMIT ceiling (4,194,304 task entries), avoiding a lower
arbitrary process cap that could reject a valid large host. An empty table or
a structurally incomplete unrelated sibling entry is ambiguity, not clearance. Malformed mountinfo rows and
unverified target identities still fail closed.
Missing evidence for an existing mount namespace, malformed, unreadable,
permission-denied, changing or ambiguous evidence fails closed.

After that read-only preflight, open the requested path exactly once with
`O_RDWR | O_EXCL | O_CLOEXEC | O_NOFOLLOW`. The requested final path component
must be a root-owned, non-world-writable block node, never a symlink. The opened
descriptor is the I/O authority; path and descriptor must also identify the
same inode (`st_dev`, `st_ino`) and not merely the same block `st_rdev`.
Before reading block zero, require `fstat()` on that same descriptor plus a
fresh path/PARTUUID-alias/sysfs/topology/mount/swap snapshot to match the
expected device, parent and exact `BLKGETSIZE64` byte count. The same opened
descriptor must report `BLKROGET == 0`; a read-only transition is an identity/
state failure, not an invitation to try another path. Geometry must be 4KiB
aligned and large enough for the authorization header plus minimum data.
Revalidate that same complete opened-descriptor identity immediately before the
only destructive operation, so a replaced symlink, stale alias, changed
PARTUUID, changed geometry, new holder/mount/swap use, parent substitution or
device disappearance cannot reach a write.

The requested O_EXCL flag alone is not proof of a kernel-exclusive admission
interval. A fake successful exclusive open establishes only the requested
flags, never BLK_EXCL behavior against real concurrent holders or swapon.
Synthetic final-gate tests must model reachable failures such as pathname
terminal-object replacement, descriptor state-query failure, or a read-only
transition; they must not manufacture an already-open inode changing file type
or make fstat() stand in for device-driver liveness. The production opener requests O_RDWR/O_EXCL/O_CLOEXEC/O_NOFOLLOW and rechecks
BLKROGET and descriptor identity. At the last prepublication gate it
independently requires fcntl(F_GETFL) to succeed and
`(returned_flags & O_ACCMODE) == O_RDWR`; failed queries preserve the kernel
errno, while an incompatible access mode refuses with EBADF. This returned-FD
check does not establish O_EXCL exclusion: F_GETFL cannot report O_EXCL, and
no additional userspace lock is acquired. Kernel-level exclusivity and
mount/swap races after the last snapshot remain UNQUALIFIED until separately
authorized loaded-kernel tests establish them.

Block zero is accepted only when it is all zero or is an exact existing SWZ
authorization header. The shared validator requires the eight-byte magic,
format version, 4096-byte header length, exact opened-device byte size, nonzero
16-byte UUID, and every reserved byte at offsets 40..4095 zero. A valid
existing header is an idempotent success only after another identity recheck,
a fresh F_GETFL check that the returned descriptor is O_RDWR, and no write.
Production-CLI rootless controls must demonstrate both the positive O_RDWR
existing-header path and negative O_RDONLY/O_WRONLY or failed F_GETFL paths
with exactly one descriptor close and zero writes or syncs. The positive
mock does not prove kernel O_EXCL holder exclusion or physical card identity. An unrecognized nonzero header is refused. A new header
starts from a zeroed 4096-byte buffer, uses a cryptographically random UUID
with RFC-4122 version/variant bits, leaves all reserved bytes zero, and must pass
`swapz_sb_valid()` before publication.

A new format attempts exactly one 4096-byte header `pwrite()` at offset zero
and then an `fsync()`; it never resumes a short successful write, retries an
interrupted write or issues DISCARD/TRIM. The write is not assumed atomic.
Once the publication call has been issued, a failed/short write, fsync failure,
post-write transport/identity/readback failure, or close failure is reported as
`UNCERTAIN` with process status 3 and requires explicit recovery before retry.
Status 2 remains a pre-publication refusal and status 1 is reserved for
operational errors where no header publication was attempted. Every
pre-publication rejection must preserve the triggering prerequisite errno
across diagnostic output and descriptor cleanup; reporting functions are not
allowed to become the returned error authority. Fail-only diagnostics name the
stage, expected condition, original numeric errno and safe next action without
exposing device paths or block contents. Admission helpers must propagate the
actual failing stage instead of collapsing topology or mount/swap inventory
failures into a generic identity refusal: the formatter distinguishes identity,
descriptor mode/state, topology and inventory at pre-open, opened-descriptor,
final-prepublication and postpublication revalidation boundaries. The explicit
`stage=` field supplements stable human-readable phase summaries; do not rename
an established summary solely to encode a more specific failing stage. A
secondary close failure must be reported separately and cannot replace the
originating failure errno.
Once publication is attempted, write, durability, identity, readback and
close failures still retain status 3 and RECOVERY REQUIRED. The standalone
formatter never creates a mapper or activates swap. After a successful write it
revalidates device identity, rereads the entire header, requires byte-for-byte
equality and full SWZ validation, then revalidates identity once more before
close. A partially written or otherwise unrecognized nonzero header is a
recovery condition and is never silently retried.

The observable identity bundle does not prove physical-card uniqueness when a
USB reader does not expose a stable card CID. PARTUUID, path, major:minor,
capacity, reader model/transport and any reader serial are consistency signals;
a substituted or exact-cloned card can reproduce some or all of them. The
current SWZ UUID cannot be repurposed as a stable per-card token because the
primary lifecycle deliberately derives that field from each transaction run ID.
A future unpredictable per-card token plus protected off-card binding would
improve accidental-substitution resistance only if it has a dedicated stable
on-card location that lifecycle formatting never rewrites; an exact clone can
still copy such a token. Until that coordinated format/lifecycle design exists,
the enforceable policy is the complete descriptor/topology/configuration proof
above, fail-closed on any uncertainty, with no claim of cryptographic or
physical uniqueness.

All package mutations and mutating primary commands, including
`qualification-import` and the `prepare/start/stop/recover` lifecycle,
serialize on the same root-owned global lock at
`/run/lock/swapz/package.lock`. Primary lock order is global mutation lock
first and target partition recovery lock second;
never acquire those in reverse order. Qualification evidence is exact-kernel
evidence: its top-level `kernel_release` must use the same restricted release-
token grammar as packaging and must equal the running Linux `uname(2)` release
at import and every later lifecycle read. A kernel change invalidates prior
qualification until `make test` and artifact qualification are repeated for
that kernel; do not infer support from a version range or successful DKMS
compilation alone. The global lock directory must be owned
by root and not group/world-writable; the lock file must be a single-link 0600
regular file owned by root, and the opened descriptor must still match the
named file after nonblocking `flock(LOCK_EX)`. Because `/run` is volatile,
the primary may recreate the exact configured lock directory with mode 0755
when it is absent, but must immediately reopen it with `O_NOFOLLOW` and apply
the same root-owner/non-writable validation before creating or trusting the lock
file. It must not create alternate lock paths. Contention is BLOCKED rather
than retried across mutable installed artifacts. Owned-null_blk qualification
redirects only this global lock to its token-bound private directory; physical
and ordinary production use the installed package lock.

Shell option changes are process-wide, even when issued inside a function. A
helper that disables pathname expansion to parse command output must restore
the caller's prior option state before returning. Later safety checks may rely
on bounded, intentional pathname expansion to find retained transaction
records; leaked `set -f` state can silently turn those globs into literal paths.

When a package transaction revalidates a pinned directory by name, compare the
named object with the already-open descriptor by inode, device, owner and type,
as well as mount identity. A same-mount directory replacement is still a path
substitution and must fail closed. Mutating primary commands must not emit a
success marker such as `PRIMARY_PREPARE=READY` until every required mutation
lock has closed successfully; a lock-close error is a failed operation, not a
successful result with a cleanup warning.

The primary manager must use the same structural PARTUUID grammar as the
standalone formatter: 8..64 characters, at least eight hexadecimal digits,
single internal hyphens only, no leading/trailing/consecutive hyphen, ASCII
hexadecimal only, and canonical lowercase output. Do not specialize this to the
current MBR-style `8hex-2hex` value because GPT PARTUUIDs remain valid inputs.
Its configuration parser, sysfs matcher and systemd-unit derivation must share
that validator/normalizer. Weak strings such as all hyphens, leading/trailing
hyphens or repeated hyphens must fail before target discovery. Config parsing
must clear caller-visible selector output before any failure, including malformed
record envelopes and overlength values, so stale authorization cannot survive a
rejected update.

The production primary-selector reader must retain the opened root-owned
configuration directory and no-follow selector descriptors until it has parsed
a local candidate and revalidated the original inode metadata against the
live named configuration directory and selected file. A regular-file
replacement or complete directory rename-and-replace must fail with ESTALE
even when the new selector has identical PARTUUID bytes, and must leave the
caller-visible target empty. The rootless production-C fixture must force both
races after reading the bytes, record before/after descriptor and named-path
identities, and prove that an unchanged protected selector remains accepted
without target, mapper or service mutation. This admission check cannot lock
a pathname against subsequent privileged changes; mutating callers still
require their existing last-use target and authorization checks.

The production primary-start transaction must pin its root-owned, no-follow
configuration-directory and selector-file descriptors *before* obtaining the
selected target, and retain both until the last pre-header mutation boundary.
The independent selector reader still validates the initial record, but it is
not a valid final transaction binding: each pathname reader establishes its own
inode baseline, so two individually safe reads can be bridged by an ancestor,
mount, or rename ABA that is restored between the caller's identity snapshots.
Before writing the header, require that the admitted pinned directory/file
metadata still matches both live names; bounded-read and parse the normalized
selector from the **retained selector descriptor** without changing its file
offset; compare those identity-bound bytes to the manifest; revalidate both live
names again; then revalidate the inspected partition major:minor, PARTUUID and
geometry. Because that target inspection is itself a race interval, repeat the
admitted selector directory/file live-identity check after it succeeds and
before closing either selector pin. Any mismatch must fail closed before header
write, mapper creation, formatter or swapon, report a redacted
phase/mismatch class and first errno, and preserve STARTING recovery ownership
and close-error precedence. Close both retained pins successfully before
destructive work. A diagnostic target
reinspection that now exactly matches the admitted target after an earlier
`ESTALE` must be classified as raced-or-restored, not falsely as a current
partition mismatch. This is last-use validation, not a kernel-atomic exclusion
guarantee against later privileged replacement or same-device-number physical
reader substitution. A privileged transient pathname replacement that begins
and ends entirely between live-name snapshots may remain unobserved, but it must
not be able to supply the selector bytes accepted for mutation because those
bytes come from the retained descriptor.
Coordinator-only admission helpers must be excluded from standalone whole-file
rootless builds whose mutating coordinator is compiled out, avoiding unused
static definitions under `-Werror`. Source-extracted rootless coordinator
fixtures must still compile and execute those exact production definitions
with synthetic temporary files; preprocessor exclusion in unrelated builds
must never replace behavioral race coverage.

The private real-swap qualification helper must bind the protected physical
selector to one context-managed O_NOFOLLOW/O_CLOEXEC descriptor. Inspect the
pathname before opening, fstat the opened regular root-owned mode-0600
single-link inode, read no more than the ASCII PARTUUID envelope (including
optional CRLF) plus one overflow-detection byte, and require matching opened
and named inode/metadata after the read. Reject short, oversized, malformed,
unreadable or substituted selector bytes; never consume a second pathname
lookup or fall back to another target. Pin the admitted selector identity,
then repeat the selector and frozen target authorization proof after per-cycle
source admission and before primary prepare. Post-read validation compares the
named inode with the still-open descriptor before interpreting unlink metadata,
so a substituted path is classified as substitution rather than an incidental
link-count change. Live authorization command failure or malformed identity
evidence at this boundary is BLOCKED, not qualification FAIL; retain the
original command status when available. Diagnostics may report only phase,
expected/observed identity category, original errno/status when present, and a
safe BLOCK action; never payload or private pathname. This helper-level check
does not establish a physical-card or reader identity lock across the
coordinator's last-use boundary. Each live target check must open the resolved
PARTUUID target with `O_NOFOLLOW|O_EXCL`, record the opened block inode,
device number and geometry, and pin a separately opened no-follow physical
parent descriptor. Require exactly one matching live partition, matching
reader topology and a unique source-bound stable reader serial; an absent
serial or conflicting reader is BLOCKED. The source-bound/live serial
comparison is byte-for-byte exact; reject an empty/whitespace-only or oversized
value, but do not invent an entropy or character-diversity threshold. A reader serial remains only a consistency signal and
does not prove a particular SD card or permit physical acceptance by itself. The initial live-target proof occurs after the private
`qualification-import`, so a refusal there reports
`owned_state_may_have_changed=true` for package-owned qualification state but
also `target_mutation_reached=false`; it must convert verifier child-command
failure to BLOCKED, preserve only its numeric status, and never disclose command
or private path text. The historical snapshot's observed `/dev/sd*` pathname
and `major:minor` describe an earlier boot, not the live target: renumbering
may be accepted only when the live plan, exclusive descriptor, parent inode,
geometry and independently bound reader identity agree. Recheck both opened
and named block inodes after policy/topology inspection, retain the campaign's
original descriptor-derived target/parent identity snapshot and compare it at
every precycle, postcycle and terminal check. The helper closes each verifier
descriptor before invoking the coordinator, so this is not continuous file-
descriptor ownership across a lifecycle command and must never be described as
such. Changed parent, substituted inode, stale geometry or unprovable reader
BLOCK before mutation; the production coordinator's own last-use descriptor
binding remains a separate mutation gate.
The existing `cycle-N` source approval occurs before `prepare`; the
parent's phase contract must not be extended by this helper. Between a
successful `prepare` and `start`, recheck the already authenticated parent's
pinned process/socket authority and live target identity. A refusal at that
boundary must prevent `start`, retain first error and completed-cycle
evidence, and explicitly report that `prepare` may already have changed
owned state. Any source change after a granted phase remains a separate
parent-owned admission boundary, not a reason to invent `cycle-N-start`. Recovery after such a refusal requires owner review
and existing coordinator paths, never automatic authorization of another
device. The parent must also reject an exited/zombie
process at every hop of a purported live privileged peer lineage. For the
accepted AF_UNIX connection, retain Linux `SO_PEERPIDFD` and bracket each
numeric /proc lineage proof with that kernel-pinned peer's liveness so cached
`SO_PEERCRED` cannot be rebound to a reused PID. An unavailable peer pidfd
is process-ownership BLOCKED with its original errno; it is not a fallback to
numeric credentials or a project-wide minimum-kernel claim. Close the owned
pidfd on every exit path. Matching PID, start ticks, session and cached
connection credentials are still insufficient to authenticate a transferred
descriptor or its later request writer. Classify this as process-ownership
BLOCKED, distinct from source-provenance failure and the still-missing
independent physical-card/reader proof.

Primary userspace mapper sizing must exactly match kernel authority admission.
After SWZ-header removal and 1MiB segment rounding, keep
`max(ceil(logical_pages / 8), 512)` GC-reserve blocks plus one independent
256-block foreground COW segment. Use division-first reserve arithmetic to avoid
overflow, reject misaligned or undersized physical geometry, and never publish
a Device Mapper table larger than the kernel will admit.

The privileged primary lifecycle is a separate authority domain. It selects a
target from protected configuration, owns transaction state and may perform
lifecycle mutation under its stronger production policy; it must not treat the
standalone formatter's command-line identity bundle as an ownership grant. The
historical physical-swap probe's older formatter invocation is retained only as
historical correctness machinery and is not a production activation path.

For the private owned-RAM `null_blk` rehearsal only, a Btrfs root source must
be identified by opening `/` and the recovery directory and matching their
kernel-reported Btrfs FSIDs, each with a single device (`num_devices == 1` and
`max_id == 1`). Do not require the mountinfo root superblock `major:minor` to
equal a Btrfs subvolume directory's `st_dev`; Linux may report different
virtual device numbers for the same filesystem. Recheck both pinned filesystem
identities and the sole member before mapping it through the physical sysfs
parent chain. This test-only exception never admits Btrfs for production or
physical backing.

The primary manager's per-transaction SWZ authorization header must be built in
memory from a freshly generated lowercase 32-hex transaction ID using the
system random source. Convert those 16 bytes directly into the 16-byte header
UUID; do not use timestamps, process IDs or caller-selected identifiers.
Populate the shared unversioned header layout and bind the **currently verified
configured target geometry**, never a fixed or historical target size. The
configured target is resolved from the protected PARTUUID selector, and its
opened descriptor, discovered device number, byte size and parent relationship
are checked at runtime. Leave every reserved byte zero and validate the
complete 4096-byte candidate with `swapz_sb_valid()` before exposing it to the
caller. Reject malformed or all-zero IDs without changing the caller's output
buffer. Header construction does not authorize a device write; the writer
remains the checked, descriptor-bound primitive after the operation owns its
durable lifecycle transaction. The one-use transaction claim is crash/ownership
metadata, not a request for another human approval.

### Primary manager module admission

The primary manager must open the retained package image at
`libexec/swapz/dm-swapz.ko` relative to the installed `swapzctl`, walking each
absolute directory with descriptor-relative `openat()` and rejecting
symlinks, non-root-owned or group/world-writable directories, and path
components such as `.` or `..`. The final image must be a root-owned,
read-only-opened regular file with one link, bounded size and stable identity.
Production APIs pin the required owner to UID 0; only the rootless test build
may use the current test owner for synthetic files. Hash the opened descriptor
against the host-qualified report, then pass that same still-open descriptor
to `finit_module()`; never hash a path and reopen it for loading. A preloaded
module is not authenticated by source parameters
or package metadata and must be rejected unless a durable manager-owned exact
load record proves its identity. The current descriptor-opening primitive
is used by qualification admission and by the checked loader. The loader must
be called only after the caller durably records and owns the `STARTING`
transaction. It rechecks the owner report, all three qualified artifacts and
the absence of any loaded swapz module or mapper, passes only
`allow_physical_backing=1`, then verifies the loaded source provenance and
read-only parameter. The kernel target independently rejects non-`null_blk`
physical backing unless it was built for `CONFIG_X86_64`; userspace release
admission is not the sole architecture boundary. ARM64 remains supported for
RAM-backed qualification and compile/native coverage, but physical admission
must stay fail-closed until that architecture receives separate bare-metal
qualification. Its ownership result remains set if post-load checks
fail, so recovery cannot hide a module that may be live. This primitive does
not authorize lifecycle execution through the CLI.

The initial one-use owner claim must durably publish the consumed run ID and
canonical `READY` stage before publishing the active partition marker. Every
device-changing operation requires both the matching active claim and a
durable `STARTING` stage. Under the permanent PARTUUID lock, reconcile only
these interruption states: exact `READY` with either a matching active marker
or no active marker, and exact `COMPLETE` with a matching active marker. Verify
the consumed record and, when present, the active record against the run ID;
atomically replace untouched `READY` with `COMPLETE` before releasing an
active marker, retain the consumed record, then allow a new run. This
metadata-only close is specific to reconciliation; it does not add a
`READY -> COMPLETE` edge to the normal lifecycle transition graph. Using an
intermediate `DISABLING` stage is forbidden because a crash there would be
ambiguous with an actual teardown. Missing or malformed provenance, an active
marker without state, or any other orphan stage remains a fail-closed
condition. Reconciliation must never perform block, swap, module, or mapper
operations. A caller starting a fresh transaction must invoke reconciliation
explicitly while holding the same lock; the owner-claim primitive itself must
refuse an existing active marker and must never silently retire a pending
`READY` transaction as a side effect of a duplicate claim attempt.

### Metadata-only primary preparation

`swapzctl primary prepare` may establish durable transaction metadata only.
Before claiming a run, require a clean synchronized main, accepted exact-source
owner qualification and live artifact hashes, persistent lifecycle storage, no
conflicting swapz module/mapper/transaction, and an identity-checked configured
target selected by the protected PARTUUID configuration. Resolve its current
partition and parent identity at runtime; do not compile a device pathname,
major:minor or capacity into the manager. The opened partition and parent must
match the owner-authorized target recorded in AGENT_CONTEXT.
The primary mapper's logical-capacity planner must use the same
`swapz_authority_capacity_window()` policy as the kernel authority for GC
reserve and foreground COW headroom; userspace must not carry an independent
copy of that arithmetic. The read-only plan must report GC reserve from that
shared helper and derive `linux_swap_kib` from the admitted logical mapper
pages, not from raw backing bytes. Raw-partition swap size remains a separate
identity check only for detecting an already-active raw swap alias. Shared
authority/codec headers are direct inputs to the `swapzctl` build and must be
declared as incremental-build prerequisites, so a capacity-policy change cannot
leave a stale manager binary.

Do not require preservation of historical card contents or an old Linux-swap
header on this disposable target. If an active swapz/ordinary-swap entry exists,
its identity and usage must be understood and safely drained before a destructive
transition. Recheck the target, parent, swap inventory and current block-zero
state immediately before the transaction claim.

After those checks, generate a fresh OS-random run ID, build the candidate SWZ
header only in memory, durably publish the transaction record, `READY` state
and active marker, then save the immutable source/artifact/device/geometry
manifest and read it back byte-for-byte. An original-header backup is optional
for this disposable SD card and must not become a production gate. Preparation
must not write the target, change swap state, load a module, or create a mapper.
Any failure after claim retains active ownership for reconciliation. The later
`start` path must revalidate the same physical card, qualification and saved
records, persist `STARTING`, and only then perform its first device or swap
mutation. Keep privileged lifecycle actions disabled until the corresponding
rootless/native/null_blk and safely bounded physical-host gates pass and
exact-source qualification is current; VM coverage is not required.

### Selector-derived systemd dependencies

The package's systemd generator must obtain unit names only through the
manager's validated protected-PARTUUID interface. Generate the escaped
by-PARTUUID `.device` and `.swap` names at boot; do not compile a block path,
major:minor, capacity, UUID or PARTUUID into a unit. The mapper service needs
`Requires`/`After` on the selected device and `Conflicts`/`Before` on the
matching by-PARTUUID swap unit, with a bounded device-job timeout. Do not use
`BindsTo` for removable media: unplugging a device must not automatically stop
a mapper that could still own live pages. Invalid selector data must not
produce a target-specific drop-in. On every generator invocation, publish
an early-priority mapper-unit mask before consulting the protected selector or
publishing target-specific units. The mask must remain effective throughout
staging and cleanup so an enabled mapper cannot acquire an incomplete or stale
dependency graph. For daemon-reload regeneration, move the prior owned mapper drop-in
into private staging until its replacement is published; a newly published
unit must not reuse a just-unlinked file identity. Require the manager response
to byte-match one canonical newline-terminated unit pair: shell command
substitution can otherwise erase extra terminal newlines or NUL bytes. Pin
the staged mapper/device inodes through rollback and unlink a published file
only when its inode still matches; a failing rename may have left a foreign
symlink or file at that path. Publish target-specific drop-ins using no-clobber
renames and verify that each destination is the pinned inode and the source
staging path is gone before releasing the mapper mask. Preserve the original
status of a failed response-comparison command separately from malformed
manager response bytes. Reject output directories reached through
symlinked ancestors, dot-component aliases or duplicate directory identities.
Validate bounded manager output, refuse duplicate generated
unit identities and symlink-substituted output paths, and remove only
generator-owned stale drop-ins from a previously selected PARTUUID.
An initial early-mask rename is not successful merely because `mv` returns
zero: verify that the mapper-unit symlink resolves to `/dev/null` and the
staging link is consumed. A failed or falsely successful rename must attempt
to restore the mask and refuse generation, preserving the original command
status and reporting rollback and any surviving temporary mask. When the
initial mask cannot be independently restored, classify an owned mask versus
foreign or unverifiable early-unit pathname, report the original transaction
status, final restore status and exact staged-rename restore status when
attempted, and require explicit operator intervention rather than claiming a
complete rollback. Before retiring
prior mapper/device drop-ins, compare their exact canonical generator content;
a matching basename alone is insufficient proof of ownership, and unexpected
regular-file contents must survive under the verified early mask.
Canonical content must be validated through a pinned inode, not a pathname that
can be replaced between comparison and retirement. Move a stale mapper/device
drop-in into private quarantine with no-clobber semantics, verify the staged
inode is the pinned inode before deleting it, and restore or retain any foreign
replacement rather than deleting it. A successful no-clobber move must
also consume the original public pathname: a staged inode match alone does not
prove retirement when a rename wrapper leaves the old name or a foreign
replacement in place. Refuse the transaction under the verified early mask
and preserve the unconsumed source without deleting foreign contents.
Overlapping invocations of this generator
against the same output directories must serialize on the early output
directory with an advisory lock held through final mask release; one invocation
must never remove another invocation's graph and then allow that other
invocation to release the shared safety mask. Lock/rollback failures must keep
the verified `/dev/null` barrier and preserve exact command status in fail-only
diagnostics.
Unit generators share these output directories and execute concurrently, so
do not treat a directory-wide scan of other generated `.swap` names as an
authoritative raw-swap inventory. Reject an already-present exact selected unit
as a collision, but an unrelated PARTUUID swap unit must not gate this
generator, and absence of another generator's file never proves alias safety.
The boot/deployment identity guard owns same-partition raw-swap alias exclusion.
The final early-mask unlink commits the generated drop-ins only when it both
reports success and leaves the mask absent. Failed or falsely successful unlink
must restore the early barrier and roll back only pinned generated inodes. A
symlink at the mapper-unit path counts as the barrier only when it targets
`/dev/null`; atomically replace a foreign substitution at that owned
early-priority safety name before reporting rollback. Diagnose the original
command status, separate restore status, expected/observed mask and drop-in
ownership, and verified rollback outcome without printing the selected
PARTUUID; shell command exit status is not a recoverable syscall errno and must
not be misreported as one.

After a first nonzero publication command, EXIT-trap cleanup must retain the
original status and independently verify each published pathname while its
pinned staged inode is still available. A zero exit from cleanup rm does not
prove retirement, and a failed rm may already have removed its target; report
the actual owned/foreign inode or symlink survivor, private-stage survivor,
verified early-mask state, secondary cleanup status, and retained-state action.
If final mask release failed and rename restoration and unlink fallback both
failed or lied, retry direct no-follow replacement at the reserved early mapper
name and verify the link is /dev/null before declaring rollback complete. Do
not follow or delete the targets of substituted foreign symlinks; absent
proof of an effective mask must be reported as incomplete, not safe.

Publish the
complete selected graph before releasing the mask; any validation, command,
publication or rollback failure must leave the mapper blocked rather than
fall back to a device path or reveal a partially active job. Diagnostics must
identify phase, selected-source category, check, original status and withheld
output, without printing protected configuration. Each fail-only generator
summary must also name the fixed mapper unit, its expected native
`swapzctl primary start`/`stop` owner and the verified or unverified early
mask state (or `not-evaluated` before directory admission). Diagnostic-only
state gates used by the refusal path must be initialized by the script before
that path can run; inherited environment variables must never enable mask
inspection before the output directories and owned mask pathname exist. A mask
inspection is not evidence of live swap state. Preserve independent
pre-hibernation refusal on failed selector admission. This dependency only names the PARTUUID
alias; the deployment gate must also prevent the same partition from being
started as raw swap through a by-UUID or other alias. Static units stay
disabled and manual start/stop remains refused until lifecycle and boot
qualification passes. The passive mapper `.swap` view, including its
`generator.early` shadow guard, must set `DefaultDependencies=no` so systemd
does not add `Conflicts=umount.target` / `Before=umount.target` and become a
second shutdown `swapoff` owner after a native manager stop failure. Preserve
the false start condition and manual refusals when a normal generator shadows
the packaged unit.

### Primary manager Device Mapper lifecycle primitives

Build mapper tables and issue Device Mapper ioctls in process; do not invoke
`dmsetup` as a privileged subprocess. Align every ioctl buffer and validate
its returned interface version, bounded lengths, target count, generated name
and UUID before interpreting payloads. The primary table is one `swapz`
target over the manifest's discovered major:minor at its maximum safe size.
Verify
its returned table parameters, one lower-device dependency, sysfs name/UUID,
logical sector count and backing major:minor before admitting use. The mapper
name is the stable `swapz-primary` path consumed by the packaged systemd swap
unit; the DM UUID includes the fresh run ID and remains the authoritative
ownership binding. A matching name with a different UUID is foreign and must
never be adopted or removed. Device Mapper ioctls may complete before udev has
published the matching `/dev/mapper/swapz-primary` node. Only after the exact
UUID/table/dev_t have already been verified through the control fd may opening
that node retry a missing-path `ENOENT` for a finite maximum of five seconds.
An existing wrong node, wrong dev_t/size, permission error, `ENODEV`, or any
other failure is immediate and must never be retried. The opened descriptor and
a second pathname identity snapshot must still match the expected dev_t and
logical size before mkswap, swapon, swapoff, or other lifecycle use.

Persist and verify the matching owner claim, immutable manifest and
`STARTING` state before mapper creation. Preserve side-effect flags when an
ioctl sequence fails so recovery knows whether a mapper may exist. Cleanup
must prove the mapper is inactive as swap, has zero open references and is
identified by the exact manifest name and run-bound UUID. It may remove only the exact
active table or a suspended partial mapper with no active table and either no
inactive table or the exact expected inactive table. Clear that inactive
table only after parsing it exactly; remove without force; then independently
prove both name and UUID absent. Unknown tables, extra dependencies, open
references, identity drift or a failed query stop cleanup and preserve the
durable recovery state. These primitives remain disabled until the complete
provisioning, activation, teardown, recovery and boot lifecycle is qualified.
Lifecycle coordinators must emit one fail-only boundary diagnostic before
attempting durable recovery-state repair, naming the current prepare/start/stop/
recover phase and the original errno. Preparation diagnostics must identify the
specific admission or persistence check that failed without exposing secret
contents, transaction run IDs or device paths. Successful commands stay quiet
except for their existing completion record, and diagnostic logging must never
replace, reinterpret or mask the original failure or recovery obligation.
Final preclaim identity revalidation and physical-parent swap inventory must
retain separate phase labels so stale identity is not reported as a swap-state
failure.

The shared transaction admission check must read the run's immutable 4096-byte
block-zero backup when the transaction records one and verify its recorded
SHA-256 before mapper creation or removal. The selected target may contain a
filesystem, an old swap header or arbitrary disposable contents; do not require
a pre-existing Linux swap signature. Missing or altered rollback bytes block
an operation whenever that transaction's recovery plan requires the backup.

## MM, folio and zswap semantic boundary

Read [context.md](context.md) for the kernel reclaim/BIO/zswap semantics and
[ROADMAP.md](ROADMAP.md) for the staged collaboration blueprint. Keep the
independently reconstructible 4KiB logical page as swapz's authority unit:
a folio, process, VMA or allocator object is not an SWZ record/extent identity.

Packing locality may only break ties among **already accepted**, authority-
safe layouts. Folio identity belongs to the WRITE-side owned BIO lifetime:
never retain a source folio pointer/reference until a later READ or compare it
with the destination READ folio. Any optional WRITE-to-READ correlation uses a
bounded, volatile, generation-checked `(logical_page, committed_generation)`
cohort association; stale/unknown mappings must not influence correctness.

A first placement candidate may permute only **equal encoded-length compressed
records after the existing greedy ordering**, never a blanket folio-first sort.
It must prove whole-window equivalence: lower bytes, bounded cold-read cost,
extent count, physical run splits/requests, segment alignment holes and tail
waste. Preserve authority publication and same-page/fence constraints. Never
wait for future work or weaken work-conserving dispatch for locality.

A zswap-origin compression bypass must depend on an explicit end-to-end
semantic handoff surviving BIO cloning/splitting; `REQ_SWAP`,
`folio_set_dropbehind` and `current` are insufficient. Tagged writeback
must use a stable RAW snapshot, terminal atomic representation ownership,
the existing CRC/generation authority and exact upper completion after
confirmed lower I/O. Skip pointless LZ4/delta64 and producer claims without
creating worker/BIO lifetime races; unknown-origin traffic retains normal
behavior. Directly accepting zswap-compressed payload requires a separate
codec/representation/read-side and ownership contract.

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

The fresh post-ID101/ID107/ID108 two-slot trial is also rejected (ROADMAP
ID110): observed depth two without a repeatable useful-service gain does not
justify extra buffers or ownership state, especially when lower requests rise.
Keep its experimental dispatch/array paths out of production. Four-record
no-follower windows retain their existing synchronous service rule.

ID114 profiling is observational only. Timing counters may sample `ktime_get_ns()`
and scheduler runtime, but must not add waits, queue ownership, dynamic
allocation, alternate representations or scheduling branches. WRITE admission
timestamps live only in the per-BIO descriptor. Synchronous four-record cycle
telemetry may observe successful K=1 commits and the gap to the next successful
four-record start; it must never hold a BIO or keep the lane busy to obtain a
sample. The internal `profile_epoch` message may clear only the passive
sync4 predecessor timestamp at a quiescent benchmark boundary; it must not reset
mapping/ordering state, cumulative product counters or alter service.
An acknowledged Device Mapper message must return 1 after filling its reply
buffer: return 0 means success without output. Keep an executable regression
of the production callback's reply and rejected-command behavior; checking only
the acknowledgement string in source cannot verify the DM output contract.
Production policy cannot change from this profiling commit alone.


### ID178 deferred-ACK accounting optimization

The worker and the existing completion work each own a separate stack-local
acknowledgement batch. An individual BIO is stamped with that batch pointer
only inside the final `bio_endio()` delivery loop and may never be touched
after completion. Sample one `ktime_get_ns()` delivery timestamp immediately
before each owned ACK cohort and use it for every successful BIO in that cohort;
publication timestamps, the successful-completion predicate and dwell histogram
bins remain unchanged. Add per-BIO counts/durations/bins to the owner-local
record and publish the aggregates to the existing `atomic64_t` counters before
the completion slot is released or preemption is restored. Direct unbatched
completions keep their per-BIO clock and atomic fallback. Successful synchronous
window completions are also one cohort; if the engine did not stamp a rare
successful mapping's publication time, reuse the cohort mark as a conservative
zero-dwell fallback rather than add a per-BIO clock read. The cohort mark is
diagnostic only: its timestamp error is bounded by the ACK delivery-loop span
and it must never move `bio_endio()`, publication, failure checks or ownership.
No unprotected shared accumulator or new queue is permitted.

After retiring ID181, the existing bounded completion handoff remains
eligible only when a lower WRITE is pending. Recheck that condition under
`queue_lock` before publishing completion work; preserve the 4..64-BIO limit,
fail-closed drain and ID175 submitter-only post-owner-release ACK ordering.
The removed publication-time exception must not be reintroduced without new
owner evidence and an explicit correctness review.

### Lower-lane gap attribution (ID178)

ID178 is observational only. No policy, ACK-delivery time, retained window,
K=1 lower-WRITE depth, on-disk SWZ representation, module parameter, queue,
allocation, lock, or wait may consult or change due to these diagnostics.
The native-tested `lane-gap.h` is pure integer arithmetic: clamp ordered
timestamps into [t0,t4], compute completion/wakeup, publication, no-work,
admitted-but-unowned, staged/held, and seal phases, and preserve the
identity that the six phases sum exactly to the paired gap. t3 is the seal
*start*: "seal" is plan, stage, pack, CRC and lower submission of the
successor, i.e. the work a seal-ahead design (ROADMAP ID179) would move off the
critical path; "staged/held" is owned records waiting before sealing starts
(retention, owner busy, preparation). A missing timestamp
or reversed completion/submit pair is invalid, not silently zero.

`struct swapz_bio_ref` retains `lane_admitted_ns`, `lane_owned_ns`,
`published_ns`, and `published_deferred` independently from the existing
ID114 `admitted_ns` and `write_admit_worker_*` counter semantics. The
ordered worker holds `ordered_owner` for its entire pass; ID175 submitter
dispatch may only take the same domain via its existing bounded trylock.
Only this ordered domain updates predecessor t0/t1/t2, foreign-WRITE
classification, gap partitions, and successor histograms. The asynchronous
completion callback writes `inflight->lower_end_ns` before completing
`lower_done`, and never owns the chronology. Each prospective run captures
the atomic `lane_profile_epoch` around t4; a generation change across that
timestamp makes the run unpaired. Publication may create a predecessor only
when the run's captured generation still equals the current epoch. The
`profile_epoch` message increments that generation before invalidating the
previous sample, so a racing old finalizer cannot resurrect a cross-epoch
predecessor. Every submission invalidates the predecessor whatever its
outcome (paired, foreign, unpaired or invalid), so a valid predecessor proves
that no run was submitted since its publication. Failure and drain invalidate
the boolean hint under ordered ownership, and resume increments the generation
so a predecessor from before suspend can never pair.

For an asynchronous run, t3 is `commit_start_ns`, taken before
`swapz_engine_prepare_batched_run()`. Its gap accounting runs only after the
asynchronous `dm_io` submission succeeded, so it adds nothing before the lower
WRITE leaves and never counts an unsubmitted run. Synchronous engine-owned
WRITE paths expose two passive observation hooks around each real lower run,
including multi-run synchronous windows: `write_sealed` marks that the exact
logical run is immutable and that the next lower WRITE is that run, while
`write_published` runs only after successful authority publication. For a
synchronous run, t3 is the window flush start for its first run (the
prepared-prefix fallback uses its prepare start) and the previous run's
publication for each later run, because the engine starts sealing the next run
immediately. `swapz_lower()` consumes exactly one sealed run and accounts it
after the synchronous WRITE returns. The hooks are inert unless a foreground
window flush opened the observation: GC compaction drives the same engine
with no window open, and its WRITEs are foreign. Those callbacks may record the
exact run-page range, a publication timestamp and per-BIO publication marks
only; they must not fail, wait, allocate, lock, change policy, or alter engine
results. An unsampled generation (a `profile_epoch` race) is inert, never an
anomaly. Gap admission/ownership scans must be restricted to that exact
successor run range; already-published prefixes are never successor evidence.

Any lower WRITE that is not a sealed window run (GC relocation, the single-page
RAW fallback) records its end time. A gap whose predecessor completed before
that end is foreign as a whole. A timestamp rather than a flag also covers a
foreign WRITE issued between a predecessor's lower completion and its
publication, while no predecessor is valid yet.

A successful upper WRITE stores publication time and deferred/immediate
classification before any completion or handoff. Because `swapz_complete()`
can run on the worker or its separate `completion_work`, acknowledgement
dwell count, nanoseconds, and histograms are `atomic64_t`, sampled before
`bio_endio()`. Synchronous lower-backed BIOs inherit the exact engine
publication timestamp instead of being stamped immediately before completion.
Histogram bounds are inclusive; `>1ms` is open-ended. Foreign lower WRITEs
are not K=1 run submissions and consume whole gaps without six-part
attribution. All counters are cumulative and only differenced at
already-established timed benchmark boundaries. Do not route results into
device policy, acceptance thresholds, or scorecards.

Any future K>1 experiment is a new architecture change, not a dormant knob. It
must restore disjoint immutable run ownership, same-page generation/order
fences, FIFO authority publication and upper-BIO completion despite out-of-order
physical completion, verified-tail-only rollback, and ordered drain across
PREFLUSH/FUA/DISCARD, GC, suspend, teardown and failure.

Physical-device support is not a coding shortcut around current safety policy.
No production/test flag may silently relax the RAM-backed owned-device gate.

Folio locality is an unqualified observation hypothesis (ROADMAP ID113 and
`docs/context.md`). Observe membership only through valid owned pages;
never retain raw folio addresses as WRITE-to-READ identity or pin original RAM
until swap-in. Any cross-I/O correlation must be bounded, volatile, generation-
checked and worker-owned, with ambiguity/eviction reported as unknown. A READ
buffer's folio identifies destination RAM, not the earlier WRITE source. Synthetic
compound-buffer coverage does not establish reclaim or application locality.
Locality must not add waits or displace complete byte/read/extent and physical-
run/tail-waste objectives. Extra tie-break CPU still requires useful-service
measurement. Larger upper BIO admission is a separate ownership change.

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
  A rejected speculative read-batch probe owns no BIOs and its count output
  is not authoritative. Restore the ordinary path's one-BIO charge after both
  probes decline; accepted batches keep their exact returned count. Zero-cost
  ordinary dispatch must not prevent budget exhaustion or turn the periodic
  reschedule check into a per-BIO operation.
  Enter READ-batch selection only for a READ FIFO head; WRITE, empty-flush
  and DISCARD heads take their ordinary ordered path without speculative
  read-slot or coalescing calls.
- **Proven-dry retained service:** an active accepted plain-WRITE wave keeps the
  existing eight-record pressure hand and effective learned/sampled target. After
  the serialized worker proves both accepted FIFOs dry and no K=1 WRITE is
  active, four staged records can close below a larger learned target only when
  no authoritative sampled target is active and the stream carries READ,
  read-bypass or wave-interruption evidence, including compressed+RAW mixes.
  A pure-WRITE stream below its learned burst width instead waits for the
  writers its previous K=1 run released, bounded by the device-relative idle
  bound; a pure-WRITE sampled tail below the learned width is not authoritative
  (`swapz_window_pure_write_below_burst`). One-record windows keep the
  original pinned deadline.
  A pure-WRITE post-PACK tail of two/three is not a finite close target; target
  four and larger still require already-accepted queued follower evidence. A
  sub-four sampled tail is finite when the current bounded snapshot observes
  an independent READ/non-WRITE boundary, or queued WRITE followers plus
  successful READ service in the same continuing PACK chain. Staged-only
  residues and pure WRITE waves retain the four-record floor; finite/hard
  closes and zero sampled tails revoke the chain mark.
  A serviced READ that occurs after a two/three-record post-PACK tail is already
  staged uses the dedicated post-pack boundary state instead. A staged-only
  post-K=1 tail with no queued follower or current non-WRITE boundary must not
  inherit earlier READ evidence as a finite close target. A prior completed
  chain or deferred valid pack alone must never bypass the pure-WRITE four-record
  floor, and no path may manufacture a one-record PACK_READY close.
- **Development hand-width control:** the production asynchronous
  work-conserving hand remains eight records. For bounded owned-null_blk
  development A/B only, a read-only module parameter may select 8, 16 or 64.
  Reject other values before target allocation and nondefault values for
  physical backing. The value is fixed for the target lifetime and exposed in
  status. This changes async early-hand eligibility, not the independent
  completion-handoff minimum, four-record service floor, ordering/fences,
  K=1 lower-WRITE depth or authority publication. A 64-record threshold
  is not a promise of a 64-record lower run.
- **Pack-readiness conservation:** `single_pack_deferred` is monotonic within
  one open window once selective compressed geometry has been proved. The
  refuted total-count-four first-pack close remains forbidden, but after total
  count exceeds four an earlier valid two-record/4KiB or three-record/8KiB
  compressed prefix must remain recognizable across interleaved RAW records and
  later compressed admissions. Both RAW and compressed admissions re-evaluate
  this finite geometry; representation order must not erase already-proved pack
  readiness.
- **Retention deadline:** learned/admitted targets may shape aggregation, but
  one retention timer bounds every retained window. Its deadline is the
  first-record deadline
  ($t_{\text{deadline}} = t_{\text{first}} + \text{retain\_ms} \times 1\text{ ms}$),
  made earlier only by the device-relative idle bound: once the worker has
  proven both accepted FIFOs dry with staged work and no lower WRITE in flight,
  the window closes at most half of one lower-WRITE service EWMA after that idle
  interval began (floored at 20us, capped at retain_ms). The bound never extends
  a deadline; a queued timer may only be moved earlier. The pre-BIO deadline
  flush uses the first-record deadline only, so an arrival at idle-bound expiry
  joins the window that the end-of-pass expiry then closes. Successful lower
  WRITEs (synchronous and detached) feed the ordered-worker-owned 1/8 EWMA. There
  is no second timer, no microsecond grace wait for a future arrival and no
  ID83 suppressed-tail wake or cache-hit pivot. A deferred sampled singleton
  uses the same deadline; ID53 remains rejected. Hard ordering boundaries reset
  retained scheduling evidence.
- **In-flight write reaping:** completed detached $K=1$ lower writes are reaped
  opportunistically inside the worker loop so upper BIOs receive `bio_endio()`
  without waiting for the full 64-BIO quantum or retention expiration. When a
  staged window or queued arrival exists at reap time, the run's successful
  acknowledgements are held on a worker-owned list until that next window has
  reached the lane (or nothing is staged, or the local FIFO is drained), so one
  lower WRITE no longer waits behind ~20 wakeups. The worker-owned list is
  emptied before any finalize wait and before the work item returns. Normally
  delivery disables preemption (`bio_endio()` is IRQ-safe). While a new detached
  lower WRITE is pending, one already-published 4..64-BIO batch may instead
  transfer atomically to a completion work item on the existing unbound
  preparation queue. That work owns its private list exclusively and releases
  its single slot after its last list/BIO access, before enabling preemption;
  it may outlive the owner callback, but never target drain/free. A busy slot,
  small batch, closed admission, failure or completed lower WRITE keeps delivery
  inline. Queue publication takes queue_lock and rechecks admission under the
  same gate that closes drain; no work may be published to a draining queue.
  Completion and DM-endio counters are atomic across these contexts. Failed
  runs are acknowledged immediately with their error, and delivery re-checks
  terminal failure at both target and DM boundaries. Terminal errors can
  arrive concurrently from the preparation and ordered workers: elect the
  first under `queue_lock`, store its immutable error and increment the
  failure counter once, then release-publish the failed flag. Completion
  and end_io acquire the flag before consuming the error; other cross-worker
  reads must be marked. Log only after releasing the lock. A per-write
  `-ENOSPC` still does not poison the target. With nothing staged or
  queued (QD1), acknowledgements stay inline. This adds no compression lane,
  I/O buffer, lower-WRITE slot or early success acknowledgement.
  Tail sampling is gated on `swapz_has_inflight(ctx)` so unfinalized completions
  never produce false empty-tail measurements.
- **Planner:** minimize lower bytes first, bounded cold-read cost second and
  extent count third. Only the adjacent lower-run writer may use the physical
  cursor/larger-class tie-break after those objectives are exactly tied.
  Default mode never adds padding bytes merely to improve alignment. Keep the
  kernel planner frame below the 1KiB warning threshold without hot-path
  allocation: pack the lexicographic physical-block/read-block/extent-count
  objective into one bounded u32 DP array. The caller's existing class/take
  output arrays may hold per-position choices during the descending DP and are
  compacted in place during reconstruction; output compaction must never
  overtake an unread logical position. The descending DP evaluates each extent
  class once and retains only its previous take for the duplicate-class
  shortcut. The adjacent writer may recompute the three bounded fit candidates
  only when its selected extent would cross a segment edge and exact-objective
  tie reconstruction is needed; ordinary planning and non-crossing
  reconstruction must not repeat fits.
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
- **Small-batch I/O:** four-record batches detach through K=1 only when queued
  preparation work can overlap; without that overlap, dispatch synchronously,
  preserving all FUA/verification and publication fences. Keep the first three
  inline-stolen pages eligible for ordinary LZ4; idle lower service may choose
  RAW on later pages using the existing stable-snapshot/atomic state rules only
  when measured inline LZ4 per page exceeds half of the per-block lower-WRITE
  service EWMA (`swapz_window_raw_hand_pays`): a RAW record costs about half a
  block of extra lower WRITE and host writes, so fast compression always keeps
  the compressed representation.
- **Pressure-hand dispatchability:** At the existing eight-record
  work-conserving hand, continue the current retained window only when the next
  already-accepted plain WRITE has a completed prepared snapshot in
  READY_COMPRESSED or READY_RAW state. Never steal an unprepared descriptor
  merely to extend the window: dispatch already-ready lower work and let the
  producer prepare the tail in parallel with K=1 I/O. Do not wait for
  compression or for a future BIO.
- **Retained READ attribution:** `retained_window_read_bypasses` may be charged
  only when a retained WRITE window is already staged at the moment lower READ
  service is issued. The worker-level `retained_wave_read_seen` mark may be set
  only after successful READ service within an active staged/continuing WRITE
  chain or behind skipped accepted WRITE followers. Cache-hit READs delimit an
  upper wave but cannot charge lower READ I/O. Continuing PACK chains preserve
  that mark, while failed/finite/hard closes and empty samples revoke it.
  Tail sampling requires a current queued WRITE follower to use the mark. Independent READs may still be
  recognized directly by the sampler's current bounded queue snapshot, while a
  READ serviced after a post-PACK tail was already staged uses the dedicated
  post-pack boundary state.
- **Block-saving deferred pack geometry:** Only compressed prefixes that save
  at least one physical 4KiB block—two compressed records in 4KiB (1 block) or
  three compressed records in 8KiB (2 blocks)—qualify as early deferred pack
  geometry (`single_pack_deferred`). Two records in 8KiB consume two physical
  blocks and remain planner-only extent geometry, never an early-close trigger.
- **Burst-target shrink after a chain:** On a worker-empty ordinary deadline,
  valid pack geometry with no authoritative sampled tail may shrink the learned
  burst target to the observed count at or above the four-record floor even
  after an earlier K=1 chain completed. A two/three-record deadline still cannot
  lower the learned floor.
- **Post-PACK READ-transparent sampling:** under queue_lock, skip only
  independent accepted READs with no staged/earlier queued same-page write,
  FUA/flush or authority conflict. Limit scans to one 64-BIO quantum; an
  incomplete scan is never a finite sampled tail. A queued READ is not a
  completed READ, so do not persist service evidence prematurely. The staged
  post-K=1 tail without a queued follower keeps its prior safety gate.
- **Serviced post-PACK READ boundary:** A successful independent READ served
  after a two/three-record post-PACK tail is already staged may make that exact
  dry residue serviceable without compressed-only pack geometry. Single-BIO,
  independent read-slot fan-out and parallel read-batch paths must all observe
  successful READ service, even while the preceding K=1 WRITE's tail sample is
  pending. Observation never authorizes dispatch before sampling completes;
  each later staged WRITE and each nonempty flush must revoke it. The ordered
  worker must prove no K=1 I/O, no pending tail sample, no authoritative
  sampled target, and both accepted FIFOs dry. Earlier READ evidence, cached
  READs serviced before the tail, singleton residues, and future-arrival guesses
  never authorize the close.
  This experiment must not add any compression-completion wait or suppress the
  qualified four-record dispatch below a larger learned target.
- **Preparation ownership:** background async preparation uses one unbound
  producer lane. The ordered owner may steal only an unclaimed next preparation
  entry while holding the admission lock. Producer and ordered compression use
  separate input/LZ4 scratch and single-writer timing state. ID150 separately
  permits an already-admitting task to claim one preallocated scratch lane and
  one existing prepared-array slot after FIFO admission; claim failure must
  fall back immediately to the established producer/owner path without waiting.
  ID169: the claim returns before touching any lane, slot or counter while a
  lower WRITE is active, so the bounded producer overlaps that preparation
  with lower service; idle-lane admissions keep submitter preparation.
- **GC destination probing:** preserve the authority's circular
  `next_segment_probe`; collection must not restart at segment zero. A
  destination remains reusable only after the existing deadness, mapping and
  role checks succeed.
- **Diagnostics:** PACK_READY causes, exact target-2/3/4 attribution,
  ready-wait counters and accepted-work lower-idle attribution are observational
  unless a separately qualified policy explicitly consumes them. Adding a
  counter is not permission to change a scheduling decision. Read them by
  their exact scope: `k1_ready_wait_*` counts only completed windows that had
  to wait for a pending lower WRITE, so zero does not mean no accepted work
  existed during lower I/O; `accepted_work_lower_idle_*` starts only when the
  owner retains a staged window with the lane idle, so it does not cover owner
  pickup, publication, sealing or the upper round trip (ROADMAP ID178 measures
  the whole completion-to-next-submit gap). The refuted ID83
  suppressed-tail lifetime state and its timer/pivot counters are removed rather
  than retained as dead policy scaffolding. Mixed-wave classification is one
  worker-owned boolean plus the sampler's existing prefix state; neither may add
  mapper atomics or admission-side scheduling. Kernel/header comments must name
  this current mixed-wave policy directly and must not retain descriptions of
  the refuted 500us wake or cache-hit close authorization.

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
field. The direct entry/exit reads do not refresh scheduler accounting. They can miss
pending execution or attribute execution from before the callback to its delta;
they are incomplete diagnostics, not guaranteed bounds on callback CPU time.
Keep separate ordered/preparation LZ4 and copy timers. Sums of LZ4/CRC/copy and
ordered commit-non-I/O timers are partial wall-time attribution, including any
involuntary preemption in those phases. They are not CPU floors or total CPU.
Do not call an unexported scheduler helper merely to sharpen this measurement.

### Synchronous READ grouping and ID63 control

The read-only `read_coalesce` parameter controls exact ID63 adjacent
compressed-range merging. Grouping and bounded asynchronous lower-READ fan-out
are fixed-on infrastructure; there is no `parallel_reads` module parameter.
Both control arms retain that fan-out, including independent RAW misses.
Eligibility follows the current exact-range/cache/dependency checks, rather
than an undocumented queue-depth or latency threshold. No helper workqueue is
enabled by these controls.

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

Fast and serial ID63 qualification varies only `read_coalesce` for five
matched rounds. The off arm must report zero adjacent-coalesced pairs and saved
requests; it may still execute independent grouped/fan-out READs. Dedicated ID39/ID60
loaded controls are removed after owner qualification/refutation; do not retain
dead benchmark sessions merely for historical telemetry.

### Page-local delta64 production routing and qualification

Whole-page delta64 is the only maintained predictive transform; the refuted
CL-delta, byte-delta, delta32, reset-delta64 and xor64 experiments live only in
Git history. The read-only module parameter `delta64_rescue` defaults to one
(owner decision; zero disables it) and is snapshotted into each target at
construction. The rescue-only second LZ4
pass uses the separate read-only `delta64_lz4_acceleration` parameter
(default 4, the ID67-qualified value, bounded 1..4); changing it must not alter
the ordinary first-pass
`lz4_acceleration` policy. Both producer and ordered
write paths must bypass the rescue call entirely when disabled; no classifier,
rescue timer or rescue counter runs and no predictor scratch is allocated for
either write or read slots. Ordinary LZ4 remains active. The codec and GC retain
delta64 encoding support; reads of an encoded record require their scratch and
fail closed if it is missing. Only an enabled target may write new delta64
records. A `delta64_rescue=0` result is not a measured classifier rejection.

Current rescue writes `SWAPZ_ENCODING_DELTA64_SHUF8`: delta64, eight byte
planes, then LZ4. Preserve decoding of plain DELTA64. Codec validation must
reject a shuffle flag without delta64, including with a valid metadata CRC;
map index 63 must round-trip with all three valid encodings. GC preserves the
encoded payload and encoding without recompression. Combined transform and
inverse reuse existing scratch with disjoint live input/output and one SIMD
entry/exit per page. Native scalar and each executable ISA backend must match
an independent byte-plane oracle. Cross-compilation is not runtime coverage.

When enabled (the default), the scalar sampled classifier runs before ordinary
LZ4. Score >=24 pages run delta64 plus shuffle and the rescue LZ4 first. A candidate at or
below 2024 bytes may be adopted directly and skip ordinary LZ4; a larger
high-score candidate falls through to ordinary LZ4 and is adopted only if
strictly smaller. Lower-score pages run ordinary LZ4 first and may enter the
threshold-16 packing-aware path only when the planner identifies an exact lower
uniform payload limit in a maintained extent class; adoption must cross that
limit and remain strictly smaller.
Portable unsigned,
memcpy-safe C delta64 is the mandatory correctness oracle and fallback.
Delta64 interprets every 8-byte word as a little-endian unsigned integer so the
stored transform is architecture-independent. Scalar loads/stores byte-swap on
big-endian hosts; numeric-lane SIMD dispatch remains little-endian-only until a
big-endian ISA backend has direct byte-exact runtime qualification. Predictor
page pointers may be unaligned, but transform input/output and combined-shuffle
scratch must be distinct, non-overlapping 4KiB buffers. Native qualification
must deliberately offset these buffers for scalar and every executable ISA
backend across the full zero, repetitive, entropy and structured corpus, not
only the first zero page. Native integer corpus words are explicitly
little-endian rather than host-endian. Native CRC32C wide-word acceleration
likewise runs only where host numeric byte order matches the byte stream;
other hosts use the portable byte-stream implementation. The native codec
tests compare aligned and misaligned CRC32C with an independent bitwise
Castagnoli oracle at empty, tail, wide-word and maximum payload lengths.

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
held above `memory.high`, allocations can trigger kernel reclaim/throttling
via `mem_cgroup_handle_over_high()` (up to 2.0s per allocation); this is a
harness artifact and cannot be equated with target I/O forward progress.
The previous Python QD-wave mixed path still allocated a `Future` and
`WorkItem` for each 4KiB request, despite the reusable pool and packed-read
optimization. Only `--resource-pressure-short` now selects the already
qualified native-C wave replay: one event/latency allocation before the
measured waves, pre-created QD32 worker threads, native wave barriers, the
same immutable ordered mixed trace and direct 4KiB I/O with byte-exact checks.
Missing native helper must BLOCK, not silently revert to Python. Maintain the
existing 280s per-candidate watchdog and the 680s pair / 720s parent bounds;
do not grant a longer deadline to conceal an actual stalled BIO.

The private ID36 packed-read path remains Python but submits exactly one
long-lived job per QD lane and reuses barriers/result slots across population,
sequential and seeded-random waves. It must not allocate a `Future`/work
item/list per 4KiB I/O or construct a temporary 4MiB joined oracle. Ordinary
non-pressure benchmark submission remains unchanged so the ID36 harness
fix cannot masquerade as a production performance change.

ID36 resource admission is evidence, not a bypass. Require two
consecutive canonical `MemAvailable` observations at the frozen 1 GiB floor.
A finite parent needs at least 1 GiB of checked unsigned-byte headroom;
`memory.max=max` still requires a readable current charge, and two absent
memory files are exempt only at a verified cgroup v2 mount root. Missing
controllers, parent limit/current charge, OOM counters, PSI or exact readiness
PID inventory are named BLOCKED prerequisites with safe observed values,
bounds and required actions, never fabricated PASS. Read high/oom/oom_kill
from one memory.events observation per decision; distinguish unreadable
telemetry from a missing or malformed required counter. Never establish a new
zero-OOM baseline without proving it equals the preceding zero-OOM snapshot,
so setup gaps cannot absorb an intervening event. CPU PSI requires one monotonic
total and valid nonnegative avg10/avg60/avg300 percentages, with the specific
negative, missing, malformed or out-of-range prerequisite named.

An observed native replay/byte-exact read-write failure, OOM, signal death
or unreaped owned child remains FAIL even if later evidence is unavailable.
Owned child cleanup authority remains retained until termination and every
parent-owned pipe descriptor have closed successfully; a pipe-close failure
after termination must keep the child in outer cleanup ownership for a bounded
retry without replacing the original failure.
Before post-pair telemetry, only an explicitly recognized prerequisite may
defer nonzero-child classification; an unclassified nonzero exit is already
FAIL and cannot be masked by a later BLOCKED sample.
Success requires both native and completed same-work pair markers. Print
ID36 PASS only after bounded cgroup/scratch cleanup, and reap only started
CPU burners against shared deadlines with owned-child TERM/KILL escalation.
Private logs are bounded; memory samples and private paths are not exposed.
Regression coverage must use synthetic proc/cgroup fixtures and fake workers,
never actual host memory pressure or privileged cgroup mutation.
Rootless ID36 admission fixtures must execute extracted production parsers and
gate bodies against bounded synthetic observations: the exact 1 GiB
MemAvailable floor and two-sample stability, finite/unbounded parent headroom
and true-root provenance, missing versus unavailable CPU/memory controller
delegation, absent/malformed OOM and CPU-PSI counters (including Boolean-like
tokens and overflow), exact ready-residency/memory.high/ramp boundaries, and
changed zero-OOM/high snapshots. Changed event snapshots must pass through the
production memory.events parser rather than injecting impossible parsed tuples.
Refused fixtures must preserve the first gate, expected/observed safe values
where the gate has a numeric bound, and unavailable evidence, while globally
rejecting any ID36 PASS marker. Source-order coverage must distinguish
controller refusals before the completed-owned cleanup call from host,
parent-cgroup and pressure refusals after the single
ID36_TMP_CLEANUP=completed-owned-only marker. These fixtures are rootless
evidence only: never use a real cgroup, host /proc observation, loaded kernel,
or reduced memory safety floor, and never present a synthetic admission marker
as full ID36 qualification.

ID36 cleanup never writes group-wide `cgroup.kill`: a membership snapshot cannot
authenticate a process that enters before the later group-wide signal. The
Bash job table is liveness evidence only, not terminating-signal authority.
Capture each direct child's canonical `/proc/<pid>/stat` start time and parent
while it is still a running job, require pidfd signaling support before
launching ID36 children, and send TERM/KILL only through a pidfd after
revalidating that captured process identity. Never signal from a previously
recorded numeric PID alone.

Pin both the newly created child cgroup and private scratch directory with open
directory descriptors, and require each descriptor identity to match the named
path immediately after opening it. Holding that descriptor prevents same-path
replacement from recycling the removed inode into the ownership proof. After
reaping, read `cgroup.procs` through the pinned cgroup descriptor with bounded
canonical parsing. An inventory containing only previously admitted/reaped PID
numbers is stale and grants no signal or removal authority; allow only bounded
departure grace and require a fresh empty snapshot before proceeding. Any
foreign, malformed, missing or unreadable observation, or any nonempty inventory
remaining after that grace, retains both the child cgroup and private session
and cannot print PASS. Revalidate the named cgroup identity immediately before
`rmdir`; an occupied or replaced group or failed removal likewise retains
evidence. A failed initial cgroup creation grants no teardown ownership. A post-mkdir
cgroup descriptor-open, inode-read or descriptor/name mismatch refusal must
record its bounded setup observation, retain the created cgroup and private
session, and publish exactly one `phase:cgroup-create` from EXIT cleanup with
the actual original status (including signal exit 143). Do not relabel that
first refusal as `phase:prior-admission` or try to remove an unpinned cgroup.
Bash descriptor-open failures for both the private session and child cgroup must
suppress shell-generated redirection diagnostics at the open site so randomized
private paths cannot escape; that suppression must be scoped to the open
attempt and must not leave stderr redirected after a successful pin.

The cooperative stop marker and cleanup of known scratch entries must use the
pinned session descriptor after confirming the named path still identifies the
created session. A verified failed pair may already have published the regular
stop marker; accept that regular file without truncating it, reject symlinks or
non-regular substitutions, and otherwise create the marker with noclobber.
Never recursively delete the session. Before deleting any evidence, inventory
the pinned directory and require every present entry to be one of the fixed
ID36 names and a regular file. Any unexpected, non-regular or unreadable entry
retains the complete session. Snapshot the validated names and unlink only
those names through the pinned descriptor; never bulk-delete canonical names
that were absent from the snapshot. A canonical entry arriving after inventory
must therefore survive to make the final nonrecursive `rmdir` refuse. Require
the directory to be empty before removal; any path replacement or later arrival
retains the remaining evidence. Cleanup
diagnostics identify phase, required ownership, observed safe category,
original exit status and retained obligation without paths or PID lists;
original FAIL/signal status takes precedence over cleanup BLOCKED. A refusal
before cgroup teardown retains both resources; after successful cgroup removal,
a session-identity or session-inventory refusal reports only private-session
retention. Partial removal of known session files must not change the earliest
FAIL or misreport a removed cgroup as retained. A final private-session `rmdir` refusal after successful cgroup removal
and deletion of all inventoried entries retains only the empty session. A
rootless regression must inject this independent removal failure, preserve the
original signal/nonzero exit and exclude any synthetic ID36 PASS marker.

Rootless regression fixtures
must inject reaped or reused PIDs, delayed departure, PID-identity mismatch,
late membership between snapshots (without any new signal authority), same-path
directory replacement, stop-marker substitution, unknown session entries and
interrupted deletion without mutating host cgroups.

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

Synchronous lower WRITE I/O blocks the ordered worker, so the producer prepares
from the FIFO head during that blocking interval. A detached asynchronous K=1
lower WRITE uses the same `lower_write_active` overlap signal but does **not**
block the ordered worker. During that interval the producer must leave a
singular FIFO head unclaimed and may prepare only a true tail, allowing the
ordered worker to continue inline from the head instead of convoying on a
producer-owned completion. The producer distinguishes the two cases from the
existing immutable in-flight K=1 state; do not add another ownership flag.

Lower READ service is deliberately not a producer wake or head-claim signal:
the qualified mixed-I/O evidence showed that rapidly preparing the small
interleaved WRITE queue can outrun accepted-work replenishment and fragment
retained windows. Outside active lower WRITE I/O, tail preparation remains
credit-limited: each ordered inline WRITE may leave at most one unconsumed tail
token. The token is earned only after the ordered worker atomically reserves its
own FIFO head. Detached K=1 tail preparation is instead bounded by the existing
single producer, 64-slot reservoir and requirement for a true tail; it consumes
no idle tail credit.

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

The ordered Device Mapper worker uses a single-active, CPU-bound
`WQ_MEM_RECLAIM` workqueue: admission, K=1 completion and upper wakeups then
chain on the submitting CPU instead of waking idle remote CPUs, which removed
most of the QD1 software gap. The LZ4 preparation worker keeps its serialized
`WQ_MEM_RECLAIM | WQ_UNBOUND` workqueue; the CPU-local preparation experiment
increased measured lower-I/O/LZ4 overlap but regressed useful mixed
throughput, lower-WRITE request geometry and worker-empty deadlines, so bound
preparation placement is rejected. `WQ_HIGHPRI` showed no measurable effect
and is not used. Both `work_struct`s remain non-reentrant system-wide;
scheduling placement never changes FIFO, publication, completion or
lower-I/O ownership.

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
invocation after the first producer drain. A producer samples admission and
publishes any ordered-worker wake while holding `queue_lock`, the same gate
that closes admission. Once that gate is closed it must not queue a fresh wake,
so the final producer drain is terminal with respect to the already-drained
ordered workqueue. A producer that acquired the gate before closure is joined
by the first producer drain, and its wake is therefore caught by the later
ordered drain.
Check the all-free mask only after this final drain. Destruction frees the array
after both workqueues. Tail
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

Page compression has a strict three-way result contract at every target-side
caller of `swapz_compress_page()`: a positive value is a compressed payload,
zero alone is the ordinary no-fit RAW fallback, and a negative errno is a
genuine preparation error. A negative result must never become READY_RAW or
enter either RAW publication path. Submitter/background preparation publishes
the exact errno before an ERROR terminal state; the ordered consumer observes
that state with acquire semantics and completes the BIO with an error. If
RAW_SELECTED already won the speculative representation race before a late
negative result exists, the producer must still fail the target closed and the
late result does not rewrite the already-selected state. Lower I/O may proceed
from the stable RAW snapshot while compression finishes, but the ordered owner
must retain its prepared-page reference and gate successful upper ACK on the
existing result_ready completion. A late negative result therefore fails that
same BIO; zero or positive speculative results permit the already-selected RAW
representation to complete. This ACK-only wait must run in a sleepable
ordered-owner path after lower publication, never inside generic or
preempt-disabled BIO completion. The inline ordered caller must unmap any mapped
input and return the negative error before staging RAW bytes. Zero remains the
only codec result that authorizes ordinary RAW fallback. On an asynchronous
codec error the producer elects target failure before publishing ERROR and must
never touch the handed-off BIO descriptor. Only READY results charge the
ready-residency gauge. An ERROR reader acquires the terminal state before
consuming the prepared-page errno and leaves BIO completion and slot release
with the ordered owner.

Native C11 race probes that claim to exercise one of these publication edges
must make the modeled payload read depend on that same acquire operation.
Scheduling-only coordination may use relaxed atomics, but no pthread barrier,
release/acquire side channel or equivalent synchronizing primitive may occur
between the producer's payload writes and the consumer acquire under test.
Synchronization after the consumer has observed the payload is permitted.
A local scalar or synthetic status that is not driven by the production BIO
completion path must not be described as evidence that an earlier ACK cannot
be retroactively revoked.

Loaded qualification may inject one synthetic codec `-EIO` through the exact
submitter, background-preparation, or ordered-inline compression owner. The
selector is an optional trailing Device Mapper constructor argument, defaults
off, is restricted to null_blk, and must be rejected for physical backing
alongside the existing lower-I/O fault controls. Injection occurs immediately
before the selected compression call, exactly once per mapping, and then uses
the ordinary negative-result path; it must not convert the error into RAW or
create a separate completion owner. Submitter and inline injection must not
submit the faulted page to the lower device. A background error may race a
previously selected RAW lower write, but the RAW_SELECTED ACK barrier must make
the upper BIO fail after the producer publishes its result. Default production
mappings pay only the predictable disabled branch and perform no fault-counter
atomic operation.


Do not expose scheduler-accounted per-callback CPU as a portable module
metric. The rejected task-cputime experiment undercounted short nonblocking
preparation callbacks on the qualification host. Partial hot-path wall attribution
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

A full-success lower run must authenticate every paused transaction against its
authority-held immutable CRC and sequence, and validate all run offsets,
record counts, RAW extents and physical bounds before replaying the first
extent. A mismatch must leave all uncertain reservations pending, deny every
upper success, and fail the serialized owner; a prior authoritative mapping is
not replaceable by an unauthenticated physical write. This preflight does not
change the committed-prefix contract for a later independently verified
payload-publication failure or the original errno/abort path for failed lower
I/O. Physical bytes written to media are never themselves publication credit.
The raw/compressed representation bit is part of that immutable identity:
one-record/one-block geometry is valid for either representation, so a
caller-side `run.raw[]` value must match authority state captured at pause
time before replay can select `swapz_finish_raw()` versus `swapz_finish()`.
Transaction CRC authentication alone does not prove representation identity.

A matching oldest sequence is necessary but not full snapshot ownership:
a damaged later transaction may fail authentication after the first has passed.
Credit lower-completed block, successful-run and extent counters only after
EVERY transaction in that run has authenticated through ordered resume and
finish or abort. Failed lower I/O may credit a credible torn prefix only after
all its snapshots have been successfully quarantined; failed cleanup credits
nothing, preserves every still-reserved younger run, and must never replace
the original lower errno with a secondary snapshot/cleanup error. A physically
completed run with an authenticated replay that later fails payload validation
still contributes its actual lower-completed blocks.

Completion accounting is a one-shot owner operation, not an idempotent counter
increment. Before counting credible lower-completed blocks or consuming any
paused snapshot, the portable completion entry point must prove that its run
still names the oldest paused sequence (which may coexist with a younger
prepared run). A stale or repeated delivery must not alter committed-lower-byte
counters, publication, or younger reservations; if the delivery also carries a
lower error, retain that original error. For batched aggregation, an impossible
completed-block count is untrusted and contributes zero completed bytes, but it
must not replace a definitive nonzero lower errno with a synthetic integrity
error. The synchronous per-extent path has the same first-error precedence:
an impossible count earns zero lower-completion credit and quarantines the
extent, but may select `-EUCLEAN` only when the lower callback reported no
original error. A definitive per-extent lower errno must also survive a
secondary authority-finish error such as `-ESTALE`: a damaged active handle
remains outstanding and must not be reported as cleanly drained or released.
The same first-error selection applies to batched replay cleanup and standalone
RAW finalization. Reporting precedence never authorizes recovery: if secondary
finalization leaves authority in-flight or paused ownership unresolved, the
mapper must fail closed rather than classify the first lower error as retryable. This guards engine replay only:
duplicate dm-io callbacks, upper BIO reference release, and the lifetime of
a reused packed buffer still require separate loaded completion qualification.


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

The ID163 fixed old-PC pilot of `count >= 4U` without queued preparation did
not establish a service gain: four-record async activity increased and QD8
requests fell, but accepted-work idle rose and the shallow-QD guards remained
unproved. Keep the existing strict count/backlog gate. A lower request count
or more async callbacks alone is not a reason to reopen this variant.

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
`swapz_engine_complete_batched_run()`. It may delegate already-published upper
BIO delivery through the single bounded completion slot described above; the
lower callback never receives that ownership.

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

Normal Device Mapper suspend must use the core's ordering boundary rather than a
target-side timing guess. swapz does not close admission in `->presuspend`.
DM core first establishes `DMF_BLOCK_IO_FOR_SUSPEND`, crosses its SRCU barrier
and waits for every preexisting target I/O to complete; only then does swapz
run `swapz_drain` from `->postsuspend`. At that point new upper I/O is already
deferred by DM before `->map`, so closing `ctx->accepting` cannot turn a
normal flush-suspend race into `DM_MAPIO_REQUEUE`/I/O error.

`swapz_drain` then cancels the retention timer, drains the ordered and
preparation workqueues, finalizes any internal lower-WRITE ownership, checks
that every descriptor/reservoir/authority owner is quiescent and issues the
required lower flush. `->resume` reopens target admission before DM core
releases deferred I/O. The same closed-admission drain remains the defensive
teardown helper for `dtr()`. Do not add fixed sleeps, delayed upper BIO
completion, or polling for an internal DM suspension flag; those mechanisms
cannot establish the core ordering boundary.


### Bounded submitter-context preparation candidate

ID150 is an execution-placement experiment, not a new representation or
authority path. FIFO admission occurs first under `queue_lock`; only then may
an ordinary task-context WRITE claim one preallocated submitter scratch lane and
one slot from the existing 64-page prepared reservoir. No allocation, sleep for
capacity, lower I/O, mapping publication or upper completion is permitted in
the submitter preparation helper. The scratch pool is capped at eight lanes;
contention or reservoir exhaustion falls back immediately to the qualified
single background producer/ordered-owner path. PREFLUSH, FUA and non-task
contexts always use that established path.

A claimed descriptor carries an atomic submitter-active gate. The ordered
worker must preserve FIFO by putting its local list back ahead of later accepted
work and returning while the FIFO head remains submitter-active. The submitter
publishes the stable RAW snapshot, optional unchanged LZ4/delta64 payload and
payload CRC before its terminal prepared state, then clears the active gate with
release semantics. The ordered worker observes it with acquire semantics.
After clearing the gate the submitter may touch only target-owned counters and
scratch-pool state; it must never dereference the per-BIO descriptor or prepared
page again because the ordered owner may immediately complete that BIO.

Submitter-prepared slots have one owner reference: the submitting task stops
touching the slot before releasing the descriptor, and the ordered consumer
returns the slot after copying/sealing it. Background producer slots retain
their existing two-reference producer/consumer lifetime because compression may
continue after RAW selection. Both paths share the same prepared-state machine
and 64-slot global bound; neither changes SWZ bytes, the four-record service
floor, K=1 lower-WRITE depth, planner geometry, allocator, GC or publication
authority.

Status must expose submitter claims, scratch/reservoir misses, active/current
peak, ordered-owner deferrals, prepared pages and submitter wall/CPU/LZ4/copy/
CRC time separately from the background producer's worker timing. These are
diagnostics only. Do not add overlapping phase walls to manufacture a CPU
budget, and do not retain the candidate merely because preparation moved to a
different task if useful service, p99, lower-I/O or resource pressure worsens.

### Idle-lane submitter dispatch (ID175)

The ordered domain (FIFO consumption, window staging, planning, allocation,
lower-WRITE submission, authority publication and upper completion) has exactly
one owner at a time, represented by `ctx->ordered_owner`. The ordered work item
holds it with `mutex_lock()` for its whole pass. A submitting task may take it
only with `mutex_trylock()` from `swapz_map()`, never by sleeping, and only for
a plain task-context WRITE (no PREFLUSH/FUA/NOWAIT, IRQs enabled) of a retained
stream that has already learned isolated closed-loop behavior
(`singleton_fast_close`) while no lower WRITE is active. Lock order is
`ordered_owner` before `queue_lock`; never take the mutex under the spinlock.

`->map` runs inside the block layer's `current->bio_list` recursion guard: a
lower BIO submitted there is only queued until `->map` returns. The dispatch
path must therefore never wait for lower I/O, a completion, a producer or the
worker. Under the owner mutex and `queue_lock` it re-proves: admission open, no
failure, a nonzero READY_COMPRESSED or READY_RAW representation (zero elision
may issue a synchronous segment DISCARD), bulk mode without verify-after-write,
no staged window, no in-flight run to finalize, no deferred single tail or
pending post-PACK sample, no other accepted or preparation-queued work, and
`swapz_open_segment_fits(&ctx->authority, SWAPZ_MAX_BLOCKS)` so placement cannot
pick or recycle a segment (GC and recycle DISCARD are synchronous). Only then
may it run the ordinary `swapz_process()` staging and an IDLE close with
`submitter_dispatch_active` set, which forces asynchronous K=1 detachment and
forbids the synchronous/GC fallback: an undetached dispatch is an invariant
violation that fails closed with `-EUCLEAN`. Any failed proof restores the
untouched descriptor at the FIFO head (`list_add`) and releases it through the
ordinary ID150 tail. The submitter lane and drain-visible active count stay held
until after the mutex is released, so `swapz_drain()` excludes dispatch.

Lower completion still wakes the ordered worker, which finalizes, publishes and
acknowledges. A dispatched run's successes are deferred to the worker tail and
delivered from a private list after `ordered_owner` is released, so a woken
closed-loop writer finds an idle owner. Acknowledgement still follows confirmed
lower completion and authority publication; failures are completed at once.
This success contract may change only with explicit owner approval; an early-
acknowledgement design must not be introduced as a scheduling or performance
optimization.
Dispatch adds no allocation, queue, timer, lower-WRITE slot, preparation lane,
SWZ change or module parameter. `submitter_dispatches` and
`submitter_dispatch_declines` are observational counters whose sum is bounded
by `submitter_prepare_claims`.

### Work-conserving opportunistic representation

The compression-cost EWMA is owned by the ordered worker and must include
completed preparation from submitter, background and inline owners. Each
asynchronous prepared page publishes its own LZ4 elapsed delta before READY;
the consumer observes it only for READY_COMPRESSED/READY_RAW. PREPARING,
RAW_SELECTED, EMPTY and ERROR do not authorize reading mutable timing metadata.
Do not update shared estimator state from concurrent preparation lanes or use a
cumulative lane total as one page's sample. Zero/unknown samples preserve the
existing EWMA. The historical `ordered_lz4_page_ewma_ns` status name identifies
its update owner, not an inline-only coverage limit. Its scope remains elapsed
LZ4 time, including scheduling, rather than measured CPU or total rescue time.

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
loses its PREPARING-to-RAW compare/exchange to READY publication, it must acquire
the resulting stable state before reading payload metadata. A failed conditional
RMW does not guarantee acquire ordering, including when its return value is
READY. The consumer's existing page reference prevents state recycling during
this bounded reread; neither waiting nor a retry loop is required.
If the dispatcher atomically
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

The same rule holds after the run's window was dispatched and before the next
window opens (empty collector, run still in flight). Such a READ must not take
the dependency path: an empty flush there waits for the whole lower WRITE and
sleeps the only ordered worker while cache hits and staged stragglers queue.
Window-scoped evidence (lower-READ bypass attribution, the deadline-after-READ
flush) still requires an open window, because an empty window has no deadline.

### Exact per-segment mapping counts

Production rotating-GC authority maintains one preallocated exact logical-map
count per physical segment. Every successful compressed/raw publication and
logical discard updates it in the same serialized authority phase as
`live_records`. Dead-segment selection and victim-role commit cross-check the
segment count against physical liveness; disagreement is corruption and fails
closed. Nonzero counts remain an O(1) rejection path. Every zero candidate must
be checked against the authoritative logical map before irreversible recycle or
victim-role exchange, even when the monotonic segment-open count, extent-class
bytes, reverse links, liveness and GC-cost sidecars all appear empty. The
segment-open counter still increments before any extent can be staged and never
decreases, but its zero/nonzero value is cached evidence rather than permission
to waive the O(logical_pages) ownership proof. The exact counter value remains
telemetry.

When logical DISCARD or zero-elision appears to remove the final mapping from a
closed segment, authority must independently prove that this page is the sole
logical-map reference before mutating the zero sidecars that permit immediate
whole-segment TRIM. The proof runs only at reclaim/final-map boundaries, never
on ordinary writes into the open segment. Portable callers without claim
history retain the conservative full-map fallback. Victim discovery/evacuation
may still scan the logical map until a separately qualified reverse index
exists.


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

GC score helpers must refuse illegal compressed physical extent classes
(anything other than 1/2/4 blocks) with zero estimated cost, consistent with
RAW validation; zero is an invalid-input sentinel, not cost-free live authority.
Native GC cost oracles must keep the prior authoritative mapping, generation,
per-segment mapped count, live-byte/I/O/min-block costs and committed-block
count unchanged after failed or short lower writes, even when a failed lower
callback reports completed physical blocks. At least one compressed short-write
oracle must stage a multi-block extent and report a nonzero strict completion
prefix; zero completed blocks alone is not incomplete-prefix coverage. Failed
or short reservations must remain absent from liveness/extent-class sidecars,
and the allocator cursor must stay beyond every quarantined block. RAW uses one
block, so its uncertainty oracle pairs a completed block with an error. These
attempts cannot earn durable relocation savings. A necessary headroom preflight
is never evidence that a subsequent reserve rotation succeeded.


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

Per-segment program/open counters describe logical allocator claim cycles.
Their exact values remain telemetry and are not NAND wear measurements. Because
the counter is incremented before staging and never decremented, nonzero remains
useful corruption/history evidence, but zero is not sufficient reclaim
authority: every zero-mapped reuse candidate still requires the independent
authoritative-map proof even if the program count and extent-class metadata are
both zero. A default-off allocator experiment may still use the exact values to compare
logical-open spread or choose the least-opened eligible destination without
additional I/O; neither that experiment nor a GC score tie break may be
described as wear leveling or authorize cold-data relocation without separately
approved physical-media evidence.

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
weaken read validation: compare the cached on-media sequence with the compact
extent-sequence index for the authoritative start block before any payload
lower read, then retain the existing logical-page, generation, payload
bounds/encoding, authority and payload-CRC checks. The observed mapping still
has to match current authority. Cold
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
Delta64's second LZ4 retains its separate read-only acceleration control
(default 4) because the rescue path has independently measured economics.

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

NEON delta64 forward processes one 64-byte line per iteration and forms each
predecessor with EXT from registers; reloading predecessors from unaligned
addresses measured slower. The NEON inverse reconstructs 128 bytes per
iteration as eight two-lane ZIP columns `[d[j], d[8 + j]]`: one serial column
scan, EXT for the upper-half carry and ADDP for the line total keep the
loop-carried chain to one add per 128 bytes before ZIP restores natural order.
At -O2 on the ARM64 development VM this measured ~70 ns/page versus ~85 ns for
the earlier per-vector EXT/DUP tree; LD4/ST4 column loads were slower than
both. Inline assembly is limited to these register permutes. The rootless
native predictor suite builds at -O1, so its backend ns/page overstate the
kernel's -O2 cost; compare variants only within one build.

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
requires a valid unchanged SWAPSPACE2 header in reserved block 0.
During the P0 metadata migration, physical backing additionally fails closed
in the DM constructor while SWZ compressed extent headers/descriptors are
written in-band. A valid swap header is never permission to publish legacy
extent metadata onto a real partition. Removing the constructor interlock
requires matching native, loaded and physical-data qualification of RAM-only
CRC, sequence, descriptor, read and GC ownership.
All mapping data and segment discard ranges start after that reserved block.
Fault-injection knobs are forbidden on physical backing. Upper WRITE completion accounting distinguishes
successful BIO acknowledgments from BIO errors; a terminally failed target
must not newly acknowledge success, even if the call site omitted the error.
No result derived from a dm status counter substitutes for a loaded direct
WRITE failure observed by a dedicated aligned O_DIRECT pwrite(2) oracle. The
oracle must distinguish the write(2) return value and errno directly; generic
copy-utility exit behavior is not the correctness boundary.
The Device Mapper target's end_io callback sees the clone status before DM
propagates it to the original BIO. It may enforce terminal fail-closed status
there but must leave any existing failure unchanged, and must not treat a
completion counter as proof of the user's write() return value.

The RAM-only compressed READ verifier must reject malformed 4/8/16KiB
extent geometry or payload offset/length crossing the extent boundary
before accessing payload bytes for CRC. A matching stale/corrupted observed
mapping is not permission to hash memory past the selected lower image.

The volatile per-logical-page authority map is part of the full-capacity RAM
budget and is currently exactly 20 bytes (`_Static_assert`). Its first
four-byte union has mutually exclusive meanings: a RAW mapping stores its
volatile CRC32C; an LZ4 or delta64 mapping stores its zero-extended payload
offset. Compressed mappings additionally keep payload CRC32C in the dedicated
RAM field; RAW mappings keep that field zero. Compressed read paths must reject
RAW mappings before examining the offset member, while the RAW integrity path
must compare the union CRC member. The shared one-byte state stores extent
size, RAW and valid flags; it is in-memory host state and must never be
serialized as an on-media structure. Transaction sequence remains extent-scoped
in the separate compact index as an 8-bit offset from the first compressed
extent sequence in each 1MiB segment. A segment contains at most 256 one-block
allocations, so the offset fits exactly; reject overflow rather than truncate
it. Clear the index whenever a dead segment is recycled. RAM-authoritative
compressed READs must not parse or authenticate a sequence from backing media.
Preserve RAW CRC, compressed offset/CRC and transaction-sequence ownership in
native production-C tests whenever this layout changes. Capacity estimates
must include the per-physical-block sequence offsets and per-segment sequence
bases, use `sizeof(struct swapz_map)` from the built source, and label
array-only totals separately from total target memory.


### Physical-smoke byte-exact oracle: opened DM identity

The private physical correctness-smoke invocation is
`device-roundtrip <mapper-path> --expect-dm-uuid <expected-uuid>`.
The UUID argument must be exactly `SWAPZ-TEST-PHYSICAL-` followed by
16 lowercase hexadecimal characters. Reject malformed or contradictory
arguments before opening the mapper; do not interpret this option as a
GC, series or default mode. Existing RAM-backed oracle invocations and
their I/O semantics remain unchanged.

The oracle preserves its existing owned-mapper pathname restriction, but
must not treat the pathname or symlink resolution as proof of identity.
After opening the mapper with its existing aligned `O_DIRECT` flags,
require one `fstat()` on the actual descriptor to identify a block device,
retain that same result's `st_rdev` as the authoritative opened identity,
and use `BLKGETSIZE64` to confirm exactly 16 MiB. Do not take a second
pathname-derived identity snapshot. In the physical invocation, read
`/sys/dev/block/<opened-major>:<opened-minor>/dm/uuid` using that retained
`st_rdev`. Require the kernel metadata to contain exactly the expected UUID
and its terminating newline, followed by EOF. Missing, unreadable, oversized,
malformed and mismatched metadata are all failures. Bound both CLI UUID-length
inspection and the sysfs read to the fixed expected identity size; leave one
extra byte of sysfs buffer capacity beyond `<UUID>\n` so an oversized value
cannot be mistaken for an exact match. Use bounded stack storage, no allocation
or per-page checks, and close every opened FD on failure.

This gate completes before any write, discard, flush or other potentially
destructive oracle operation; a same-sized but wrong-UUID mapper must never
reach the byte-exact workload. The helper independently owns mapper
creation, post-create identity checks and separately authorized physical
qualification. This oracle gate does not itself authorize physical I/O.

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
lower WRITE path is actually idle, before the selected pressure hand, and only
when the active batch plus unclaimed preparation queue already prove at least
that many accepted records. Production/default selects eight records; the
owned-null_blk development A/B may select 16 or 64. For retained operation, the
current effective learned/sampled target must also be no larger than that
pressure hand; if policy will keep the wave open beyond the selected hand,
forcing an early record RAW cannot start lower I/O and only sacrifices
compression. Non-retained
operation remains immediately dispatchable. QD1/QD4 and later records in a
larger wave therefore retain their inline compression opportunity. Once K=1 is
in flight, remaining accepted work keeps its compression opportunity so
producer/ordered preparation can overlap lower service.

Eight records are the qualified production pressure hand, not a maximum run
size. The development selector may raise that hand to 16 or 64 without changing
the four-record floor. The worker refreshes accepted followers from incoming
before evaluating local readiness.
A retained work-conserving hand may not split an already-accepted plain-WRITE
FIFO below the effective learned/sampled target merely because the next
representation is not READY. When the accepted FIFO is genuinely dry, an
undersized pure-WRITE retained batch remains on the existing pinned retention
deadline unless a complete multi-pack hand of at least eight records is already
staged. A finite mixed-wave sampled target is serviced at that exact target
instead of being converted into a timed wait. Non-retained operation keeps the
historical immediate work-conserving behavior.

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

### RAW READ fan-out

The existing eight private READ slots may serve independent authoritative RAW
pages as one-block reads, under the same staged/in-flight/earlier-queued-WRITE
and fence checks as compressed records. Keep RAW out of SWZ adjacent coalescing,
header decoding and cache prime/seed/absorb. Reset the slot representation on
reuse, join every submitted lower operation before reuse, and verify each RAW
page through the authoritative CRC before copying it to an upper BIO. Callbacks
report lower completion only; the ordered worker retains completion and mapping
ownership. Merge read accounting once on success and failure. No extra READ
workers, buffers, RAW cache or lower-WRITE depth is authorized by this path.

### Published completion handoff verification

Published completion handoff accepts cohorts of 4 through 64 BIOs. Its minimum
is independent of the eight-record early-dispatch hand and its development
overrides. Keep a dedicated completion constant; changes to dispatch width
must not silently suppress already-published ACK handoffs.

The unbound completion item shares the preparation queue and has no dedicated
CPU measurement. Scheduler boundary deltas may misattribute its execution to
later callbacks on that pool worker. Moving
completion work is not proof of total CPU savings. Both completion loops can
include IRQ service; timers ending after preempt_enable can include scheduling.
Use explicit phase/scheduler evidence when attributing their cost. The private
loaded gate must prove positive handoffs, bounded drain across suspend, exact
upper completion counts, final bytes, and fail-closed writes after a later
injected lower error. Native tests compile actual target bodies for the close-
before-publication and release-before-reuse interleavings; fake queue primitives
do not replace kernel lifecycle/resource qualification.


### Runtime primary health and hibernation boundary

The systemd runtime-health path is an observer, not a second lifecycle owner.
It must not call `swapon`, `swapoff`, mapper removal/creation, formatting,
`swapzctl primary start` or `primary stop`, or mutate recovery authority.
The native primary manager remains the only owner of swap activation and
deactivation. A failed native stop may be followed only by an ignored,
read-only diagnostic that reports retained mapper/swap state without retrying
or hiding the native failure. The active oneshot mapper service with
`RemainAfterExit=yes` must report `SubState=exited`, while its passive active
`.swap` reports `SubState=active`; an observed contradictory substate is FAIL,
not HEALTHY. Missing or invalid substate telemetry is DEGRADED unless another
check proves failure. Preserve the originating bounded `systemctl` exit for
unavailable substates and label service evidence as observed or inferred. A
successful probe with blank or multiline substate output is observed malformed
telemetry with command status zero, not a fabricated command failure or inferred
state. Bind passive `systemctl is-enabled` text to its documented exit semantics:
`static`/0 and `disabled`/1 are the only admitted safe pairs; a mismatched pair
is incomplete evidence, not proof of safe enablement.

Production observation is bounded to low-frequency polling (normally 60
seconds) and logs the first snapshot plus state changes and confirmed failures,
not repetitive success. Bind the mapper to the ACTIVE run ID and exact selected
backing identity, then observe active swap inventory, target terminal/error and
lower/logical I/O counters, GC progress/headroom pressure, occupancy/remaining
capacity, backing availability, mapper/passive-swap unit state, and attributable
kernel errors. Once the configured PARTUUID parses successfully, an absent
by-PARTUUID path is a definite backing-device failure even if its prior
major:minor can no longer be queried; preserve the parsed identity long enough
to report that distinction. Missing or uninspectable telemetry for an existing
device is degraded/incomplete evidence; it never authorizes destructive
recovery. Sustained GC-stall reporting requires repeated pressure/headroom
evidence without GC victim/page progress. Once the existing bounded consecutive
stall threshold is reached, runtime health must latch FAIL and emit exactly one
operator stop-required marker naming normal primary stop; the observer must
continue collecting evidence and must not invoke swapoff, mapper removal, or any
lifecycle mutation itself. A monitor restart or successful normal lifecycle
teardown is the boundary for clearing that process-local latch. Cold-boot
capacity verification must
independently reproduce the kernel/manager admission boundary: the GC reserve is
`max(ceil(logical_pages / 8), 512)` physical blocks and one additional
256-block foreground COW segment must remain outside the advertised logical
mapping. A zero-headroom maximum or capacity derived directly from raw backing
bytes must fail boot verification rather than being accepted as equivalent
geometry.

Cold-boot verification treats nonzero read-only `dmsetup info`, `table` or
`status` exits as unavailable evidence even when their stdout resembles
a valid mapper identity or healthy target. A multiline mapper UUID is
ambiguous and cannot be accepted by examining its first line. Passive swap
enablement is admitted only as `static` with exit 0 or `disabled` with exit 1;
text/status contradictions block arm/preflight authorization and remain
INCOMPLETE when encountered by the post-boot observer. Only documented
activation-capable pairs (`enabled`/0, `enabled-runtime`/0, `alias`/0,
`linked`/1 or `linked-runtime`/1) are definite FAIL observations; unsafe-looking
text paired with another exit status remains unavailable/inconsistent evidence.
Fail-only,
path-free diagnostics must name the observation phase, expected and observed
state, original failed-probe exit, authorization-consumption disposition and
safe report inspection/rearm action. These checks never mutate swap or mapper
state.

Hibernation/resume is unsupported because primary swapz mapping authority is
volatile across a fresh boot. Arming and boot preflight must fail closed when
kernel, initramfs, boot-loader, sysfs resume, or persistent swap aliases select
the swapz mapper/backing device or an ambiguous automatic resume target. The
systemd generator must add read-only pre-hibernation guards to hibernate,
hybrid-sleep, and suspend-then-hibernate paths; daemon-reload regeneration must
preserve that boundary. Once a valid primary target is configured, hibernation
is refused for the entire configured interval rather than only while an active
swap row happens to be visible. The mapper's first pre-start check must also
refuse recovery/activation while any hibernation-capable systemd unit is active
or activating. These two read-only checks close both check/activation race
directions without automatically stopping swap or rewriting sleep settings.
An unresolved device/tag resume alias is unsafe whenever a selected swapz
identity exists; only a provably distinct canonical identity may be admitted.
Do not broadly disable unrelated suspend settings or rewrite administrator
configuration: reject the unsafe path with diagnostics.

 
### Primary swap observation fail-closed boundary

Treat `/proc/swaps` as a complete kernel inventory, not an unchecked list
of paths: require the exact five-column header and valid rows, normalize
space/tab field boundaries, and distinguish an actually empty inventory
from unreadable, truncated, or malformed data. Inability to prove swapz
inactive must deny pre-hibernation admission without executing any
swap/mapper operations. A syntactically valid active block-swap row with an
unresolvable device identity is not proof that it is unrelated to swapz and
must also deny hibernation, including when the primary target selector is
absent. A resolved Device Mapper alias also requires readable sysfs DM-name
identity before its active swap can be ruled out. Keep that classification
bound to the major:minor captured from the active swap entry; never re-resolve
a mutable by-id/by-UUID pathname to infer a later kernel identity. Verified
unrelated swapfiles remain permitted. Unreadable current kernel command-line evidence
must likewise deny resume admission. A live mapper without provable selected
backing/run authority is a failure, not a degraded optional metric.
Runtime health must also inspect every active partition-swap row, not merely
count rows that resolve to the expected mapper. Unresolved block or Device
Mapper identity and missing sysfs DM name leave incomplete evidence
(DEGRADED when those are the only defects). A nonzero bounded probe exit
also invalidates its stdout even when it looks complete; missing run-bound
mapper identity remains a definite FAIL rather than optional degradation.
An active selected raw backing partition or competing primary mapper identity
is a definite FAIL. A matched primary mapper row must be a partition swap at
priority -1 and its usable Size must equal the validated DM logical bytes divided
by 1024 minus the 4 KiB swap header already enforced by boot verification. A
different type, priority or capacity is a definite FAIL even when a later
inventory recheck reports an apparently healthy row. Compare each alias using
its captured major:minor while
permitting verified unrelated swapfiles and unrelated resolved block devices.
Emit bounded, path-free observer phase/check, expected state, classified observed
state, original probe exit status and a read-only next check only when the
reported state changes; never promote missing evidence to HEALTHY. Confirmed
nonzero canonical DM `error` must have a structured `target_terminal` / `first_error`
diagnostic retaining the validated signed errno and original status-probe exit.
The target's canonical `error` domain matches `swapzctl`: zero or a negative
Linux errno from -1 through -4095. Positive, out-of-range or noncanonical values
are malformed telemetry and must not be promoted to a terminal-error FAIL. The
bounded parser must compare the parsed magnitude with 4095; a decimal digit-count
shortcut must not admit values above the errno ceiling. A separately valid `failed=1` remains a definite target
FAIL even when its error telemetry is malformed. Missing or malformed error
telemetry must not fabricate first-error attribution. Reject
duplicate swap sources and impossible Used-greater-than-Size accounting as
malformed inventory. Because alias identity is resolved after the proc snapshot,
a HEALTHY or inactive conclusion must re-read the normalized inventory and
require the same rows; a changed or unreadable recheck is incomplete evidence.
Keep repeated kernel-journal queries capped to a small recent-error window,
use portable case-insensitive matching, and report cumulative error counts
from DM status separately from the recent journal window. Never log raw
kernel-journal content: even filtered swapz messages can include private
transaction or configuration paths; emit only fixed, path-free categories and
a read-only inspection hint.

Production root helpers must use an explicit system executable search path and
C locale rather than inheriting caller-controlled lookup semantics. External
status probes used by a long-lived observer must have a finite per-command
deadline so a wedged `dmsetup`, `systemctl`, `journalctl`, `lsblk`, or
`blkid` cannot permanently stop health sampling. Test-only executable paths
must require the existing explicit rootless-test marker and a separate fixture
path.
