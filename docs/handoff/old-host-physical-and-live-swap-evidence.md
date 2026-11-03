# Historical old-host physical and live-swap evidence

This file preserves the detailed physical-swap and live-swap evidence from the
retired `/dev/sda4` development host. It is **historical evidence, not current
operator policy or an active deployment path**. Current target identity,
authorization, lifecycle gates, and completion criteria are canonical in
[AGENT_CONTEXT.md](../AGENT_CONTEXT.md). The historical recovery protocol remains
in [live-swap-trial-recovery.md](../live-swap-trial-recovery.md).

The two records below were migrated from `docs/ROADMAP.md` without rewriting
their substantive evidence. The pre-migration ROADMAP is preserved at commit
`c4aedff05ac7f67b5793fef4bbf553be1d3a0365`; Git history remains the
authoritative transcript if later summaries differ. Issue #76 references in the
records concern the retired host and do not recreate its one-use approval model.

## Owner-requested physical swap-partition smoke — bounded correctness only

**2026-11-02 PHYSICAL CORRECTNESS SMOKE: PASS (HOST-REPORTED;
BOUNDED CORRECTNESS ONLY).** Run
`94e5cd3f2c15d6ff52587d568e8d11f5` executed on bare-metal x86_64
from 09:27:34 to 09:27:52 PST, with qualified production source
`651c35bb5023a69e8a8b42f1113b8a9beaf3c7f6` and helper-policy
commit `841c2bb8c4c4e6b064fe857eaabb976d4c596cdf`. The exact bound
artifact/helper hashes were verified by the operator, and the final
read-only plan admitted active swap with 0 KiB used. All 11 physical
device-roundtrip invocations returned PASS, covering the 128-page
byte-exact baseline, delta64 write/verify, segmented and cross-
representation verification, and THP write/verify plus ordinary verify.
Post-phase mapper identities and status observations passed.

Original Linux swap was restored on /dev/sda4 (8:4, PARTUUID
`7fb9401d-04`): 16777212 KiB, priority -1, and 0 KiB used at the
09:28:27 PST observation. The restored 4096-byte header matched the
original SHA-256
`ace016a7a3ecd22b0aca05946a305aef2113bc50439452756ae68909010f0afe`.
Recovery state was durably COMPLETE; the owned mapper and dm_swapz
module were absent, before/after unrelated DM inventory was identically
empty, the partition marker was absent and the one-use approval remained
consumed. Root-owned evidence remains under
`/var/lib/swapz/physical-recovery/swapz-physical-94e5cd3f2c15d6ff52587d568e8d11f5/`;
`results.json` SHA-256
`da71b3642824b63ecaa7db43e6fb65baf19cfaefa8cc4fbf2b13d075eb893865`.
These device outcomes are operator-reported, not independently read
from that root-owned evidence directory by this GitHub-side review.

The host's journalctl rejected --kernel, so retained dmesg fallback
records were unfiltered. The operator separately examined the exact
run interval and observed only two informational initialization lines,
with no swapz warning/error attributed to this run. Older messages in
the fallback must not be treated as run failures. The earlier physical
attempt `5c4f825bc3bab808e128b2fc66a58f74` remains FAIL with zero
oracle phases, its recovery COMPLETE and its approval consumed; its
evidence has not been rewritten. This PASS does **not** qualify
performance, endurance, broader physical media, or production use.
No additional physical attempt is approved or necessary to establish
this bounded correctness milestone.

**HISTORICAL 2026-11-02 FOLLOW-UP: NORMAL SWAP RESTORED (OWNER-REPORTED).**
The authorized supervised recovery for run
`5c4f825bc3bab808e128b2fc66a58f74` removed only the owned mapper,
unloaded dm_swapz without force, restored the original 4096-byte header
(SHA-256 `ace016a7a3ecd22b0aca05946a305aef2113bc50439452756ae68909010f0afe`),
and reactivated ordinary swap on 8:4 at 16777212 KiB and priority -1.
The recovery state is COMPLETE, the active marker is absent and the
consumption record remains. Post-reactivation usage reached 720900 KiB,
which does not invalidate normal-swap restoration. The original physical
smoke remains FAIL because no oracle phase ran.

The preserved results.json incorrectly records
`restored_swap_verified=false`: the observation path compared against
capacity and priority omitted from the identity-only recovery target.
The durable saved state contains those expected values, and the
independent restoration checks passed as reported. Do not rewrite the
historical results or imply the physical smoke passed. The host did not
support journalctl's --kernel option; unfiltered dmesg included older
error messages predating the 08:15 physical module load. Their cause
remains undetermined, not established as a swapz physical-test failure.
The recovery-coordinator's initial logging-call error occurred before
device operations; a separate read-only verification preceded the
corrected invocation. A post-recovery whole-partition hash was stopped;
the original 4 KiB header was reverified. No further physical smoke is
approved, and zero-used swap would again be required before one.

**HISTORICAL 2026-11-02 RECOVERY INCIDENT — PHYSICAL TESTS HALTED.** An approved
one-use run cleared and SWZ-formatted the selected partition, loaded
dm_swapz, and created the expected 16 MiB mapper. A colon-delimited
dmsetup information row triggered a false identity failure and later a
false mapper-absence result; rmmod failed while the mapper was in use.
The physical mapper and module remain loaded, original swap is inactive,
the saved formatted-header digest is still present on block zero, and
the intact 4096-byte original header backup is retained. No oracle
phase ran. The consumed approval and active recovery marker must remain.
Before ANY further physical test, separately supervise a live recovery
review proving exact device/mapper/UUID/table/lower identity, module
provenance and a matching original backup. No force removal, reboot,
manual header overwrite or standalone recover bypass is approved.
A helper-only parser fix and green CI cannot certify that live recovery
was completed.

The owner authorized one bounded physical correctness round-trip on the active,
zero-used swap partition, with swapoff limited to that exact selected partition.
This remains outside ordinary make test and establishes no performance,
endurance, NAND-lifetime or general physical-media qualification.

**Historical pre-run disposition (2026-11-02): OWNER QUALIFICATION PASS ON 651c35bb;
PHYSICAL RUN STILL BLOCKED BEFORE DESTRUCTIVE WORK.** The latest x86_64
five-stage owner PASS is published by report-only commit e88c3038.
At last inspection the selected normal swap was active with 0 KiB used,
its original size/priority and matching block-zero digest. The first
approved invocation stopped before swapoff because a successful
`dmsetup info -c --noheadings -o name,uuid` returned `No devices found`,
which the helper incorrectly parsed as a malformed mapper row. No swapz
mapping, formatter, module or physical oracle ran; restoration was not
required. The approval for run 5e7d0aa53634b792f5b399cf7ced2d2e is
void and must not be reused. Fix only the empty-inventory parser, add
rootless regressions, then require green current-HEAD CI, a fresh
device-bound one-use verbal approval and a positive read-only plan.
No additional owner `make test` is required if the qualified production
binaries and source-to-HEAD exemption remain valid.

Admission is limited to bare-metal x86_64; the helper must reject VM and
container execution and fail closed if `systemd-detect-virt` is missing or
inconclusive.

The owner-supplied x86_64 five-stage PASS report was inspected from
test_results.json at report commit 74d8521bd2202481b39ce450d519432844dfc4fa.
It qualifies production source fa0875c96a2f401461a2538301c14dff5c691db4 and
publishes the following artifact SHA-256 values:

- swapzctl: c917bfcb064576b84efea07c2fcec693b8199ccbbf78761aec6d626f58dd212a
- dm-swapz.ko: e9001e487e3a86f2404c716f69bb01aa4cc4676f4a5f869201468d1a91850d67
- device-roundtrip: 2bd79246f5524c00ed06752c66b770a6a15532451e981b9a8cb93f9446ec2b8f

All three live artifact files match those hashes. Two earlier same-host x86_64
five-stage PASS reports for source db9e90536551 have the same three hashes.
They are repeated evidence of the same built artifacts, not additional
same-source qualification requirements. A new owner make test is not requested.

The helper policy is being narrowed to require at least one complete latest-
source owner PASS with qualified artifact digests, and to admit earlier
qualifications only when all three hashes match. Post-qualification commits
are limited to the physical helper, its rootless regression, this testing
standard, this roadmap and report-only test_results.json publications. Reject
merges and every other changed path; any production source, oracle C or build
input change requires new owner qualification. Rehash the live artifacts again
immediately before the run and execute only recovery-directory snapshots.

Remove SSH-signature verification and bind the supplied verbal approval text
as a strict, duplicate-key-rejecting JSON record with approval_mode verbal,
reviewer openai-chatgpt-external-reviewer, qualified source, current helper Git
commit and SHA-256, all artifact hashes, exact UUID path, major:minor, PARTUUID,
size, original 4096-byte header digest, scope and unique one-use run_id. Verbal
approval is procedural and is not cryptographic authentication or proof. Keep
the permanent consumed-run record, partition lock and durable active-recovery
marker. The current helper-policy commit must have green non-privileged
GitHub CI before the read-only plan gate.

The fixed /var/lib/swapz/physical-recovery base must be root-owned mode 0700,
beneath root-controlled parents, on persistent physical storage and not on the
selected swap partition. The helper validates storage and identity. Persist and
fsync the original header, recovery state, reviewed artifact snapshots and a
bounded results.json before swapoff or block-zero writes. Results retain the
timestamps, hashes, selected device identity, original swap row, mapper
identity, per-phase return/output and dmsetup/block-stat observations, final
header digest, final swap row, recovery state, and mapper/module/unrelated-map
cleanup status. Never record raw page contents.

After a read-only plan shows every device, source, artifact, recovery, verbal
review and unconsumed-run gate positive, one helper run may execute the bounded
positive correctness sequence: the opened-DM-UUID byte-exact round-trip,
delta64 write/verify, segmented write/verify and ordinary readback,
cross-representation readback, and THP/compound-folio write/verify/readback.
Reverify exact mapper identity before and after each invocation and record
dmsetup status and selected-partition block statistics. A failed phase stops
the suite and immediately enters recovery; never retry it with the same
approval.

The helper must remove only its exact mapper, unload only a positively
same-process-owned module, restore and reread the exact original 4096-byte
header, reactivate only the original partition with its original size and
priority, durably mark recovery COMPLETE and remove the active marker. Preserve
the consumed approval and all recovery/results evidence. Final success also
requires an absent helper mapper, unchanged unrelated mapper inventory,
safe module cleanup, matching original/restored header digest, the same active
swap major:minor/size/priority and no outstanding active marker. Any mismatch,
unexpected state or recovery uncertainty stops the run and requires review.

Excluded from this first physical round: performance/endurance work, synthetic
failure injection, fault ordinals, DISCARD/TRIM, 4096-page rewrites, GC or
resource pressure, timing-dependent suspend/drain and emulated storage-rate
models. Results remain correctness evidence for that one partition/run only.

Critical path:
verified owner report and live hashes -> narrow helper policy plus rootless
regressions -> push policy commit and require green GitHub CI -> verify or
create only the fixed recovery base -> bind a fresh one-use verbal record to
the current helper commit and exact device -> require a fully positive
read-only plan -> one bounded physical run -> exact recovery/restoration proof.

## Historical old-host full-capacity and live-swap qualification

At the time of these records, the mission was to qualify the maximum safe
logical capacity backed by the complete `/dev/sda4` partition, then prove actual Linux swap-out/swap-in,
GC/churn, shutdown, recovery, and rollback on this physical PC. The earlier
11/11 physical-backed byte-correctness smoke remains a separate bounded pass;
it did not activate its mapper as system swap and did not qualify live swap.

The source geometry gives an authority admission limit, not yet a verified
production capacity. `/dev/sda4` is 17,179,869,184 bytes. After the one-block SWZ
header and rounding down to 256-block (1 MiB) segments, 4,194,048 physical data
blocks remain. With the current `ceil(logical_pages / 8)` reserve rule, the
largest admitted logical target is 3,727,872 pages: 15,269,363,712 mapper bytes
and 14,911,484 KiB of Linux-usable swap after its first header page. The
authority reserves 465,984 blocks (1,908,678,144 bytes) for GC. Under the
24-byte `swapz_map` layout used by this historical source revision,
capacity-index arrays are 132,398,304 bytes (126.26 MiB), excluding fixed
caches, scratch, worker state and allocator overhead. The native boundary
regression now passes through production authority C, including rejection of
the next page and initialization of all capacity-dependent authority arrays.
It does not establish that the loaded target can allocate, reclaim or sustain
GC at this new maximum. The previous loaded maximum-target constructor and boundary probe
ran on exact source `6ff945e8c5e6671f9ffd6d1920343190ae1e5e28`, whose authority
used the older `ceil(logical_pages / 4)` policy and admitted 3,355,136 pages
(13,742,637,056 bytes). That owner `make test` and its report-only publication
`d6c1edca3ea21836e01ad0a8c087bfda4aeaf470` remain valid historical evidence for
that older limit; they do not qualify the new `/8` maximum. No owner `make test`
has yet qualified this capacity-policy change.

On that older source, the loaded maximum-target constructor used an owned
RAM-backed lower sized to the then-usable geometry. Device discovery recorded
667,648 mapper logical READ bytes before the probe's own data phase; their
userspace source was not identified. Constructor lower statistics and physical
READ/WRITE counters remained unchanged. The boundary probe verified byte-exact
writes and reads at logical page 0 and the old final admitted page, using only
two 4 KiB pages of data and revalidating the opened mapper UUID and full table.
Its reported lower deltas were 24,576 READ bytes and 8,192 WRITE bytes, with
zero target failures. This confirms bounded old-limit boundary addressing; it
does not fill the volume or qualify sustained maximum-size writes, worst-case
RAW occupancy, GC or Linux `swapon` behavior. The historical qualified artifact
hashes are formatter
`7f38c6f4226142ceb0c655009f0917d7370ccd0aac7a5db110148b1a861e00e0`, module
`e9001e487e3a86f2404c716f69bb01aa4cc4676f4a5f869201468d1a91850d67`, and
oracle `f47c6f9c9ca97d4d580e0a2d88efcb41cca8d34f4a35e0456a4a4d9a6e85ffe8`.
The probe uses only owned RAM-backed `null_blk` and does not write to the
user's live swap partition.

During this `make test`, a read-only `lsblk` inventory was run during the late
SD read-coalescing matrix. Because `lsblk` may probe a newly created mapper,
late performance samples may include observer I/O; do not use them for a
performance conclusion. The maximum-capacity boundary phase had already passed
before that inventory. At the post-run check, `/dev/sda4` remained ordinary
swap on 8:4 with priority -1 and the original header hash, with no swapz mapper
or module. Usage was 4,316,828 KiB at the immediate post-run check and
3,942,280 KiB in a later read-only snapshot; both were nonzero. At that later
snapshot `MemAvailable` was 8,733,600 kB and memory PSI `full avg10` was 0.97%.
The zero-used live-swap admission gate remains blocked; the pages must remain
under normal Linux swap.

**Historical old-host record.** Issue #76's live-swap supervisor carried the
owner's 2026-11-02 decision for one bounded no-fallback trial on the previous
computer: swapz as the sole swap area on `/dev/sda4` at the
maximum admitted capacity (3,727,872 pages, 15,269,363,712 bytes), at most 30
minutes, with RAM below 50 percent before the original swapoff and one bounded
cgroup swap-pressure check inside the window. The owner waived the separate
external-review requirement for this one trial. No reviewer approval exists in
the repository, and the waiver is recorded as an owner decision. Execution is
enabled only for an approval bound to a CI-passing HEAD. Whether the trial
produced real swap-in and swap-out is recorded in its results, not assumed here.
This is not production readiness: persistent boot integration, sustained GC and
churn, and physical power-loss recovery remain unqualified. Loss of the volatile
swapz mapping authority still means pages already stored through that mapping
cannot be reconstructed.

No fallback swap is required by owner decision. A swapfile on root F2FS
(`/dev/sda3`) would share the same USB physical device as `/dev/sda4`, so it
could not protect against loss of that device. Reopen fallback only if the owner
asks for it.

The primary systemd manager is being developed in native userspace C and its
package units remain disabled. `swapzctl primary plan` reports the maximum
capacity arithmetic and strictly parses `/proc/swaps` to report the active
entry count and target size, priority and use. It also performs read-only
by-UUID/by-PARTUUID/device identity, exact-size and original swap-signature
checks when run on the host. The direct-C fixture disables those live reads.
It verifies the original 4096-byte header against the recorded SHA-256 digest.
It checks recovery-directory ownership/mode, an allowlisted persistent
filesystem, direct separation from 8:4, and an absent active marker. Its
read-only sysfs checks separately resolve the recovery and target partitions
to physical parent devices, require direct physical-partition backing, and
reject virtual/stacked sources or nonempty holder lists. It reports that the
recovery directory is on the same physical USB disk as the target, so this
state is persistent across process exit but does not protect against failure
of that whole device. Btrfs remains excluded until multi-device ancestry can
be verified. It also strictly parses mountinfo, confirms `/dev/sda4` is not
mounted, and resolves the root mount to a direct physical partition distinct
from 8:4. It reports separately that the root and recovery filesystems share
the target's physical USB disk. It also inventories `/sys/module/dm_swapz` and
`/sys/block/dm-*`, requiring the module and all SWAPZ-namespaced mappers to be
absent. Exact runtime ownership, swapz target table/capacity, and the lifecycle
remain unchecked, so the plan stays BLOCKED. Provision, activation, teardown
and recovery are disabled.
The installed mapper service now orders before and conflicts with the exact
UUID-generated systemd swap unit for `/dev/sda4`; package installation still
leaves both swapz units disabled and does not alter the host's fstab.
Its condition and uninstall guard now use the same stable
`/var/lib/swapz/physical-recovery/primary-state.json` location as the durable
state-record primitive. No lifecycle command writes or consumes that file yet.
The earlier Python manager draft was removed because production Python is
outside this repository's coding standards. The remaining implementation must
integrate the permanent root-controlled PARTUUID lock primitive with each
lifecycle operation and add durable state transitions, initial provisioning,
checked restoration, startup-failure rollback, exact mapper/module ownership,
and interruption recovery. Lock acquisition and durable one-use owner-claim
primitives now have direct-C regressions. A bounded state-record replacement
primitive now uses file fsync, checked atomic rename and directory fsync, with
rootless symlink/update tests. No primary lifecycle command uses the lock,
owner claim or state replacement yet. No live swap or boot integration has
been qualified through this manager. Do not enable its units until those paths
and the exact-host qualification gates are closed.

The native manager now has strict canonical parsing and formatting for its
small durable lifecycle-stage record, plus a run-ID-aware transition predicate
that preserves original recovery provenance. Its state writer checks the
permanent lock and exact owner claim, rejects illegal transitions, and uses
the durable replace primitive. Owner release requires a matching `COMPLETE`
state, removes only the active marker, and preserves the consumed record.
Rootless coverage exercises these paths, including rejection of a competing
lock and a new run after completion. The record is only a stage envelope, not
the immutable device/artifact/backup recovery manifest. A per-run original
4096-byte header backup now has an exclusive-lock/claim-bound writer, atomic
no-replace installation, fsyncs, SHA-256 verification and a strict reader with
rootless round-trip and tamper-refusal coverage. The immutable manifest now
binds run ID, qualified source commit, userspace and module artifact digests,
qualification-report digest, fixed partition identity, original-header
digest, maximum logical capacity, and exact generated mapper identity and
table. Its parser is canonical and fail-closed; its writer and reader require
the owner claim and lock and enforce durable no-overwrite installation and
verified readback. Rootless regressions cover round-trip, invalid source
digest, fixed-identity tampering, no-overwrite, and output preservation on
failure. These storage and format primitives do not prove that supplied hashes
came from accepted qualification evidence. No privileged lifecycle command
uses these primitives yet; qualification-evidence validation, provisioning,
mapper ownership, startup rollback and recovery remain unimplemented and
unqualified. Fixed-size manifest fields are validated within their declared
buffer bounds before formatting or filename construction.

The next checked-restoration primitive now accepts only a read/write descriptor
for the fixed 8:4 target with exact 16 GiB geometry, compares the complete
current 4096-byte header with an expected value, writes the replacement with
short-write handling, fsyncs, and proves exact readback. Its rootless fixture
uses a temporary regular file and confirms stale-header refusal. The API
is paired with a fixed-path exclusive-open helper that checks `/dev/sda4`, the
UUID link, and PARTUUID link before and after opening the UUID path with
`O_RDWR|O_EXCL`, and checks the opened block descriptor's identity and exact
geometry. Rootless alias tests verify same-target acceptance and substituted
target refusal using temporary files. They do not prove block-device
exclusive-open semantics, physical geometry, or recovery behavior. The
immutable manifest primitive now exists, but qualification-evidence validation
and lifecycle integration are still required before use. Privileged execution
remains disabled.

Header digests now use an in-process SHA-256 implementation instead of
spawning `/usr/bin/sha256sum`; rootless tests cover empty and `abc` vectors, a
known multi-block digest, and overflow refusal with preserved output.
The bounded artifact-FD hasher rejects writable, unsafe-mode, hard-linked,
oversized, or changing regular files and preserves its output on refusal. Its
rootless tests pass, but no primary lifecycle or qualification checker uses it
yet.

The root build now embeds the committed Git source SHA and a production-input
clean/dirty bit in `swapzctl` and `dm-swapz.ko`; `swapzctl primary plan`
reports both values and whether the loaded module agrees with the control
binary. The kernel publishes its values through read-only parameters and
module metadata. DKMS packaging carries the generated header into its owned
source tree so a later DKMS compile uses the same provenance. Rootless
regressions require exact, clean source equality and reject dirty, mismatched,
invalid, and unknown identities. These values are evidence inputs, not
qualification: the manager still needs an accepted owner-report reader, live
module/userspace artifact hash comparison, and lifecycle integration. This
build-input change alters both qualified artifacts, so a fresh exact-source
owner qualification is required before any primary live-swap execution.
The initial native CI run caught that unconditional provenance-header writes
triggered an unnecessary `swapzctl` rebuild in the repeated-build contract.
Header generation now uses a same-directory temporary and atomic replacement
only when the bytes change, preserving both failure safety and incremental
build reuse.
The DKMS lifecycle regression now supplies deterministic private provenance
within its sandbox and verifies that the installed source manifest contains
the exact header used to compile the packaged control binary; production
package metadata remains fixed to the generated in-tree header. The first
native CI attempt caught a missing copy of the committed fallback header in
the synthetic incremental-build fixture; the fixture now includes that input
and the source-tree contract is documented.

The primary userspace now parses a bounded root-owned
`/var/lib/swapz/physical-recovery/primary-qualification.json` report. The
reader requires the exact five PASS stages, source SHA, x86_64 machine-id
digest and three qualified artifact hashes. The read-only plan now hashes its
running `swapzctl`, the package-matched round-trip oracle and a byte-for-byte
copy of the qualified module retained under `libexec/swapz/dm-swapz.ko`, then
exposes each digest and its match against the owner report. The package tracks
that retained module image in ownership/tamper checks; a DKMS rebuild is not
substituted for it. Rootless fixtures accept a matching report, reject
host/source and stage mismatches, malformed JSON, trailing bytes, duplicate
required keys,
nonzero stage exits and invalid artifact hashes, and ensure host artifact
paths are unavailable in the fixture. An explicit root-only
`qualification-import` command verifies the source report, host, all live
artifact hashes, persistent recovery base and inactive manager state before
atomically storing it. Replaced reports are retained by their digest.
Rootless store tests cover replacement, preservation, repeat store and
active-marker refusal. The manager now has a descriptor-relative package
module opener that walks the installed path without symlinks, rejects unsafe
directory/file ownership and permissions, pins a single-link regular file,
hashes that descriptor against the qualified module digest and returns the
same read-only FD for a future exact load. Rootless regressions cover digest,
mode, hard-link, final symlink, parent symlink and traversal failures. The
read-only plan and qualification import now use that same path opener and
expected report digest. A root-only checked loader now revalidates the host
report and all artifact hashes, refuses a preloaded module or swapz mapper,
loads the exact pinned FD with `allow_physical_backing=1`, and verifies loaded
source provenance and the parameter readback. Rootless tests prove the loader
is unavailable and strict boolean parsing. No CLI lifecycle operation calls
the loader yet; a caller must first persist and claim `STARTING`, and must
retain recovery ownership when a post-load check fails. Privileged lifecycle
commands remain disabled. Source parameters still cannot authenticate a
module loaded by another actor; lifecycle admission must reject such modules.

The primary manager now has a manifest-derived Device Mapper table builder and
an in-process ioctl layer for creating, verifying and removing the maximum
safe-capacity `/dev/sda4` mapper. The mapper uses the stable name expected by
the packaged systemd swap unit and a run-bound UUID. Verification checks both,
the active table parameters, exact logical sector count, one lower `8:4`
dependency, sysfs identity and backing relationship. Removal refuses an
active swap entry, open references, deferred removal and unknown table state;
it handles a suspended mapper left before table resume only when its inactive
table exactly matches the manifest, and proves both generated name and UUID
absent after non-forced removal. Focused ASan/UBSan tests cover table-buffer
construction and malformed or misaligned response rejection; a strict
production userspace syntax compile covers the ioctl path. No real ioctl,
mapper, module load or swap operation ran. The API and CLI execution gates
remain disabled, and this change modifies `swapzctl`; it requires fresh
exact-source owner qualification before it can be used. The loader and mapper
primitives are not yet integrated into a complete prepare/start/stop/recover
state machine, and no boot lifecycle is qualified.

The next primary-manager slice adds operating-system-random transaction IDs
and pure construction of the fixed-size SWZ authorization header bound to the
run ID and `/dev/sda4` geometry. Rootless tests validate the exact UUID bytes,
reserved-zero region, shared header validator and output preservation on
invalid input. This is format-construction groundwork only: no partition was
written, the privileged lifecycle remains disabled, and cold-boot recovery,
swap activation, stop/recovery integration, exact-source qualification and
live swap-I/O evidence remain open.

The one-use owner-claim primitive now persists its consumed run record and
initial `READY` state before publishing the active marker. A later claim can
reconcile interrupted metadata-only `READY` claims with either an exact active
marker or no active marker. It also releases an exact `COMPLETE` transaction
whose active marker survived interruption. Every path verifies permanent
consumed provenance and atomically closes untouched `READY` state to
`COMPLETE` before releasing ownership. It never deletes the consumed record or
touches the device. Missing provenance and other orphan stages fail closed.
Rootless tests model both `READY` interruption windows, the
`COMPLETE`-before-marker-release window and missing provenance. This closes
only metadata-claim crash accounting.

A production-only metadata preparation path now verifies the qualified source
and live artifacts, persistent recovery storage, exact original `/dev/sda4`
identity/header, any active selected-target alias as zero-use and unambiguous,
root/mount separation, and absence of a loaded module or existing mapper.
Unrelated swap entries are permitted and remain untouched. It constructs the
future SWZ header in memory, then durably claims a fresh run and stores/read-verifies
the original header backup and immutable manifest. It performs no target,
swap, module or mapper mutation. The global privileged lifecycle gate remains
disabled, and the path has not yet received its isolated-VM interruption
coverage or a new exact-source owner qualification. The prepared-start coordinator is now wired behind the still-disabled global
execution gate. It revalidates the exact READY transaction, qualification,
artifacts, target/topology and inactive selected-target swap state before
persisting STARTING; only then may it write the run-bound SWZ header, load the
qualified module, create/resume and format the run-bound mapper. Native swap
activation is now also wired behind the gate: the coordinator pins and
revalidates that exact mapper, invokes ordinary swapon through its descriptor,
then requires exact /proc/swaps proof before it may persist ACTIVE. Any
post-STARTING failure is durably marked RECOVERY_REQUIRED while the owner lock
remains held. Module loading now also has a durable per-run
write-ahead ownership record: INTENT is fsynced before `finit_module()`, then
atomically advanced to LOADED only after loaded-module verification. This gives
stop/recovery durable provenance instead of inferring ownership from sysfs
parameters alone. Normal stop is now wired behind the disabled gate: it durably
enters STOPPING, uses native swapoff when the exact run-bound mapper is active,
requires exact inactive inventory proof, then removes only that mapper,
non-forcibly unloads only the module proven by that run's LOADED record,
verifies the run-bound SWZ backing header, and persists RESTORED/COMPLETE before
releasing the owner marker. It deliberately leaves the disposable card in SWZ-header form
rather than restoring historical raw content. Standalone recovery is now wired
behind the disabled gate: it accepts exact RECOVERY_REQUIRED provenance plus
recoverable durable STARTING/ACTIVE/STOPPING/RECOVERING/RESTORED states left by
an abrupt process exit. After validating manifest/header identity it first
normalizes those states to RECOVERY_REQUIRED with the first interrupted stage
preserved. It recognizes only the saved original or run-bound SWZ block-zero
bytes, enters RECOVERING before cleanup, deactivates the exact mapper with
native swapoff when necessary and proves it inactive before remove/prove-absent,
then unloads only a manifest/WAL-proven module (with INTENT accepted solely for the
finit_module interruption window). It rechecks block zero after cleanup before
RESTORED/COMPLETE and owner release; failures return durably to
RECOVERY_REQUIRED with the first interrupted stage preserved. Definite
swapon/swapoff syscall failures are never treated as success; only EINTR may be
reconciled by exact post-operation inventory. The global execution gate remains
zero. The rootless direct-C suite now injects fake syscall and swap-inventory
adapters into the same transition helper used by the native wrappers, covering
success, definite failure, EINTR reconciliation, unreadable post-operation
inventory and raw-backing refusal. Its independent Python lifecycle model is
supplemental. This covers the bounded syscall/inventory decision logic only. The loaded
qualification now also schedules a separate exact-source owned-null_blk
success-cycle rehearsal through the production coordinator: a real RAM-backed
partition/PARTUUID, private exact-artifact qualification, READY prepare,
run-bound module/mapper creation, native swapon, ACTIVE, native swapoff, mapper
remove/module unload and durable COMPLETE with host swap identity restored.
This closes the no-interruption coordinator execution gap once owner `make test`
observes its PASS marker. The private owned-null_blk build now also has
production-elided deterministic process-death hooks after STARTING, module WAL
LOADED, mapper resume, swapon-before-ACTIVE, STOPPING and swapoff. The owned
null_blk lifecycle rehearsal now drives all six hooks sequentially, verifies the
expected stale durable/kernel state, then invokes normal recovery from a fresh
process and requires COMPLETE with preserved interruption provenance, permanent
consumed evidence, no mapper/module, and byte-identical host swap inventory.
This evidence is produced only when the exact-source owner make test loaded
stage observes the new six-case PASS marker. Bounded physical live swap, cold-boot
recovery, boot integration, workload performance and production qualification
remain open.

Mapper lifecycle admission now also reads the per-run original-header backup,
checks its SHA-256 against the immutable manifest, and verifies the Linux swap
signature before allowing mapper create or remove primitives. Rootless direct-C
coverage accepts the valid fixture and rejects a disallowed stage, altered
backup, and missing backup. A digest override is confined to that test
translation unit; the production digest remains fixed to the qualified host.
This closes a rollback-evidence gap in the mapper primitives, not the missing
start/stop/recovery coordinator or any live-swap, boot, performance, crash, or
production-readiness gate.

The primary manager now has a separately gated Linux swap initializer for the
verified mapper. It pins the root-owned `mkswap` executable, supplies the
already identity-checked mapper through an inherited descriptor, requires the
durable transaction to be in `STARTING`, validates the v1 swap header against
the exact logical page capacity, and verifies the original `/dev/sda4` SWZ
header remains unchanged. Direct-C rootless coverage checks valid and malformed
swap-header fields and confirms the privileged operation stub remains
unavailable. No mapper formatting, `swapon`, or `/dev/sda4` mutation was run.
This `swapzctl` production-source change requires fresh exact-source owner
qualification before use. The full primary start/stop/recover coordinator,
interruption recovery, boot integration, sustained-GC behavior, and production
readiness remain open; packaged units and the global privileged execution gate
remain disabled. The focused direct-C regression first caught a strict-compiler
warning from the ten-byte magic declaration; the validator now compares the
ten magic bytes while excluding the C string terminator.

Post-format mapper operations now use the persistent by-PARTUUID path plus
`/dev/sda4`, because replacing the Linux swap signature can remove the
content-based by-UUID link. The helper allows that link to be absent only when
the opened partition has a valid SWZ header; the lifecycle caller must also
match its run ID. When the by-UUID link is present, it must still resolve to
the same opened partition, and dangling or substituted links fail closed.
Rootless coverage includes an original header without the link, the valid SWZ
header, dangling alias and mismatched alias. This closes a path-resolution gap
in the new initializer, not the missing lifecycle coordinator or any
physical/boot qualification.
