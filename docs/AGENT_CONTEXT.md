# Agent operating context

This is the compact, **always-loaded** operating contract for engineers and
agents working on swapz. It is the first document to read after every fetch of
`main`, after any documentation change, and before a destructive host action or
major architecture decision. Longer documents remain authoritative references,
but retrieve only the sections needed for the current decision.

## Mandatory ordinary Linux swap partition design (2026-11-09)

Real backing must be an existing, valid SWAPSPACE2 Linux swap partition.
Never repartition, run mkswap on, or rewrite its header, UUID or partition
table. After a safe swapoff and exact-exclusive admission, only the data
area after the protected 4096-byte first page may be used. The newly
created virtual Device Mapper mapper alone may receive mkswap.
Switch between ordinary swap and swapz with verified swapoff/swapon,
without reboot. An active selected partition may have nonzero `Used`; PREPARE
records that ordinary-swap policy instead of requiring an artificially empty
partition, and START lets the kernel `swapoff` migrate live pages before any
exclusive mapper mutation. After a successful trial, obtain the owner's choice:
keep swapz active or return to ordinary Linux swap.

All swapz-specific record and extent descriptors, offsets, lengths,
generations, CRCs, mapping/segment allocation and GC metadata must
be bounded volatile RAM state. The production kernel's compressed extents
now contain payload bytes and deterministic padding only; the legacy
serialized codec and synthetic SWAPZ001/null_blk fixtures are not physical
partition formats or production metadata authority. Preserve 4/8/16KiB
packing, readback integrity, ordering, concurrency and fail-closed semantics.
Physical and production acceptance remain blocked until current-source
loaded, fault-injection, lifecycle and real-partition tests qualify this path.

Earlier permissions to format/repartition even the dedicated SD card
are superseded; only post-swapoff swap *data* may be overwritten.

## ARM64 qualification boundary

The ARM64 VM completed all five RAM stages of `make test` at source
`88d8d84fcb51`, then full RAM/integration qualification at clean source
`40e55fdca6e1` (`make test_full`, exit 0; report `ff440ffbeaed`). These are
historical source-bound results, not admission for a later source revision.
Real-partition backing remains intentionally x86_64-only in the kernel and
production qualification/host checks. The algorithm selector and privileged
probe now reject unsupported partition trials before new ownership or native
swap drain; pending same-boot cleanup remains available. An ARM64 port must
separately qualify architecture, host identity, exclusive partition admission,
unchanged SWAPSPACE2 header, real swap integrity, capacity/GC and lifecycle.
Do not remove a platform gate or reuse a null_blk test seam to obtain a trial.
The dedicated-card and separate Lubuntu authorizations below do not transfer
to the VM.

## Current production mission

The project goal is to make swapz production-ready for ordinary
**non-hibernation** swap on the current dedicated physical development PC and
configure it as the default swap implementation backed by the dedicated SD
card.

The current owner-observed target is:

- partition path: `/dev/sda1`
- partition major:minor: `8:1`
- size: `124787884032` bytes
- current filesystem/signature UUID: `8c6a02a2-20e9-4e31-869a-48ef7f6c990b`
- PARTUUID: `f13428f6-01`
- parent: removable USB Multi-Card reader, approximately 116.2 GiB

The primary manager selects its target from the root-owned
`/etc/swapz/primary-target` file, which contains one `PARTUUID=<value>` line.
Keep device paths, major:minor values and capacities out of production source
constants. The manager resolves and checks the selected partition at runtime,
then binds its PARTUUID, discovered major:minor and byte size into the
transaction manifest. To move the goal to another drive, update the protected
selector and this owner-observed target record after confirming the new
partition and parent; do not patch C constants. The current authorization
still applies only to the target identified above, and lifecycle execution
must remain disabled until the manager's parent checks and physical acceptance
cover the selected target. The packaged systemd source derives the selected `.device` and by-PARTUUID
`.swap` names only through the manager's validated selector interface. The
generator adds exact device ordering and the raw by-PARTUUID conflict without
embedding a host path or capacity. The selected udev `.device` job has a 30s
timeout; a separate 300s mapper-job bound allows the manager's 120s start/stop
and kernel swapoff grace. The mapper service requires the persistent
qualification-evidence location because it reads the signed report there; that
mount is not lifecycle ownership or partition recovery. Mutable ownership is
same-boot tmpfs state under `/run/swapz`. The service runs
`preflight -> recover -> prepare -> start`, where `recover` is legacy command
naming for same-boot lifecycle reconciliation only and never rewrites or
restores the raw swap header. It deliberately does not `BindsTo` removable
media. `swapzctl primary start` already performs
`swapon` and `primary stop` performs `swapoff` and safe owned mapper teardown.
Therefore the mapper service alone is WantedBy=swap.target and MUST be enabled
only after qualification; the `.swap` unit is a passive view of the active
swap and MUST NOT be enabled or started independently. The passive `.swap`
sets `DefaultDependencies=no`, including through the generator shadow guard,
so systemd does not add its automatic `umount.target` shutdown stop; the
manager remains the only swapoff owner even if its normal stop fails. Clear
any legacy enabled `.swap` wants symlink
before deployment. Units remain disabled and manual start/stop of the mapper
and passive swap are refused until the lifecycle is qualified.

`packaging/swapz-primary-boot-verify` implements the fail-closed
`arm`/`preflight`/`observe` harness. It persists root-only evidence under
`/var/lib/swapz/boot-acceptance`, binds the next boot to boot ID, kernel,
protected PARTUUID, target geometry/parent identity and installed-module
provenance, and rejects active/configured raw-swap aliases by resolved block
identity, including unresolved block-device entries and second mapper
activators. The verifier never enables, removes, or deactivates swap.
Arming requires a stable removable-reader serial or WWN and a persistent
qualification-evidence filesystem. That evidence store is not lifecycle
ownership or swap recovery metadata and does not need a physical-parent
separation relationship with the swap partition. On the next boot, the verifier checks
armed identity again, exact run-bound mapper UUID, ACTIVE transaction state and
matching durable owner markers, full DM table/geometry, the primary mapper's
`/proc/swaps` entry at priority -1 (unrelated host swapfile entries are
allowed), healthy services/counters and relevant kernel errors.
PASS/FAIL/INCOMPLETE evidence is committed to disk before the observer returns
0/1/2 respectively. No same-boot PASS is possible. Reader serial does not
establish the identity of the SD card itself: physical acceptance remains
independently required.

The partition path and content UUID are observations, not sufficient identity.
Before destructive work, prove that the opened partition and parent are the
same authorized removable card by geometry, partition/parent topology,
major:minor, stable parent attributes available on the host, and descriptor
identity. Any observed UUID/PARTUUID or partition-layout change must block
admission; formatting, repartitioning and replacement identities are forbidden.
Never substitute
whatever later happens to be named `/dev/sda` or `/dev/sda1`.

Only the positively identified SD card's post-swapoff data area is disposable.
Its existing SWAPSPACE2 header, UUID and partition table must remain untouched.
Bounded data-area writes and DISCARD/TRIM remain permitted under the current
exact device ownership gates, but no raw formatting or repartitioning is allowed. No other
physical disk, partition, filesystem, mapper, or swap area is in destructive
scope.

Use the whole authorized partition as physical backing and expose the largest
logical swap capacity that remains correct for incompressible payload data,
alignment, GC reserve and forward-progress reserve. Extent metadata resides
in RAM, not the partition. Do not advertise capacity
that depends on favorable compression.

## Standing owner authorization

The owner decision recorded on 2026-11-03 replaces repeated per-run owner or
external-review permission requests for physical work on this **current
dedicated SD-card target**. Agents may autonomously use sudo, create/remove verified swapz mappings, run swapoff/swapon for the verified
target, perform bounded real-swap qualification, and install deployment
configuration when the technical gates for that operation pass.

This standing authorization does **not** weaken:

- exact device and parent identity checks;
- source/artifact provenance and qualification;
- mapper/module ownership checks;
- active-page protection and normal `swapoff`;
- fail-closed handling of ambiguous or torn state;
- bounded memory/CPU/queue behavior;
- correctness, data-integrity, GC and lifecycle acceptance criteria.

Historical `/dev/sda4` one-use approvals and issue-76 trial records remain
immutable evidence for the earlier computer. They are neither the host-scope
record below nor authorization for this machine. The dedicated `/dev/sda1`
authority above remains unchanged.

## Separate Lubuntu host scope for `/dev/sda4`

The owner separately authorizes the second Lubuntu computer to use only its
`/dev/sda4` partition as a possible swapz target. This partition shares the
SanDisk USB parent with that computer's root (`/dev/sda3`), boot and EFI
partitions. This is a different host authority from the dedicated-card
authorization above. Never transfer a device number, PARTUUID, geometry,
parent identity or qualification result between the two computers.

The same-root-parent policy may be admitted only by a root-owned mode-0600
`/etc/swapz/primary-root-parent-scope` record inside a root-owned,
non-group/world-writable `/etc/swapz` directory. The exact two-line record is
`schema=swapz-primary-shared-root-v1` and `scope_sha256=<lowercase sha256>`.
Its digest binds a combined hash of this host's DMI product UUID and
`/etc/machine-id`, the live root partition, selected target PARTUUID and
partition number, both partitions' device numbers/start/size/type/table
identity, parent device number and size, a hash of stable parent
serial/WWN/vendor/model identity, and a hash of the complete non-overlapping
partition-table layout. Including the hardware UUID prevents the bootable USB
disk's machine-id alone from carrying this authorization to another computer.
The manager re-collects and compares these facts through sysfs, root-owned
udev data, and an opened, geometry- and PARTUUID-checked target descriptor at
admission and immediately before the first raw target write. It reports only
bounded status and error categories;
it never prints the host machine-id, serial/WWN, record contents or raw
identity fields as diagnostics. The read-only plan may print the single
SHA-256 scope fingerprint needed to provision the exact record. That is a
non-secret binding value, not permission; the manager never creates or
replaces the record. Missing, malformed, replaced or mismatched records
preserve the default same-parent refusal.

This host-scope record does not authorize the parent disk or any sibling
partition, and it does not by itself qualify, prepare, start or install
swapz. All source, artifact, loaded, physical data-integrity, lifecycle and
deployment gates remain mandatory. A separate persistent "recovery" disk is
not a swapz requirement: the backing `SWAPSPACE2` header is immutable and
swapz mapping authority is volatile, so there is no swap header or payload
image to restore after reboot. Mutable run ownership belongs in root-owned
same-boot RAM-backed state under `/run`; persistent qualification/build
evidence may remain outside the swap device but must never become data-path
metadata or a physical-parent admission dependency. Any production path that
still requires `/var/lib/swapz/physical-recovery` to be on another physical
device is obsolete P0 migration debt, not a safety requirement. No fallback
swap area is required or implied.

No fallback swap is required. Do not create or modify unrelated storage merely
to provide fallback. If the authorized card is unavailable or cannot be proven
safe at startup, fail to a clear **no-swap** state rather than substitute another
device.

Codex/automation must never intentionally reboot, panic or crash the PC. The
owner performs reboots. Hibernation/resume remains unsupported because swapz's
mapping authority is volatile.

## Development-velocity policy

This PC and SD card are dedicated to swapz development. Prefer the shortest
safe path to a correct maintainable product:

- fix the highest production blocker instead of adding ceremony;
- use direct native-host evidence when it is safe and more informative;
- reuse only the authorized swap partition's data area after safe swapoff,
  preserving its original header, UUID and partition table;
- remove obsolete approval gates and recovery complexity that exist only for
  the older shared-swap experiment, while retaining technical safety gates;
- reuse valid evidence instead of rerunning expensive qualification without a
  reason;
- use `make fast_test` for development decisions, `make test` for algorithm
  RAM checks (physical qualification remains fail-closed), and `make test_full`
  for exact-source rootless integration and RAM checks; RAM evidence is never
  physical- or boot-acceptance evidence;
- use `make fast_test RESUME=1` after interruptions or unrelated main advances;
  it reuses only matching private input/artifact checkpoints and always reruns
  the current product build and loaded preflight;
- when early card-backed data-path evidence is needed before full
  qualification, use only the private physical helper's explicit
  `--development-only` mode: bind a fresh current-main `make fast_test` record,
  require the card already inactive, run one bounded mapper round-trip, and
  verify the original SWAPSPACE2 header stays unchanged while leaving the card inactive. This is
  experimental debugging evidence, never physical acceptance or a production
  readiness result;
- investigate a failure to cause before repeating it; never rerun until one
  sample passes and hide the failures;
- avoid VMs, fallback infrastructure, unnecessary dependencies and broad
  refactors unless the product itself requires them.

Dangerous fault injection is separate from ordinary real-swap testing. Never
deliberately invalidate volatile mapping authority while unrelated desktop or
application pages depend on the mapper. Use rootless models, production-C tests,
owned RAM-backed `null_blk`, or controlled non-system mappings for failure
modes whose expected result could strand pages or hang/panic the kernel.

Real swap tests on the physical card must use bounded workloads: dedicated test
processes/cgroups where practical, fixed allocation limits, timeouts,
`MemAvailable`/PSI/OOM monitoring, swap-usage bounds and early-stop thresholds.
A failed mapper `swapoff` is a stop condition; never force-remove it.

The quantitative physical acceptance policy is frozen in
`docs/production-acceptance.json`. Both the native real-swap helper and the
dedicated-SD performance evaluator consume that file directly and fail closed
on drift. The handoff readiness snapshot is observational and may lag this
policy file; its historical `NOT_FROZEN` field does not override the canonical
frozen manifest.

## Main synchronization contract

**Standing owner directive: `main` is the ONLY permitted development and
publication branch. No agent or Codex session may create or use any other
local or remote branch, including temporary, experimental, CI, backup,
`agent-*` or `codex/*` branches. No pull requests of any kind, including
draft PRs, PR-based qualification, or PR-based merges, may be created or used
for current work. No secondary worktrees or forks. This applies to GitHub
connector/API actions and CLI commands, not only to conventional Git use.**
The root [AGENTS.md](../AGENTS.md) is the mandatory short entry point for
every coding agent and contains explicit forbidden operations.

Existing old branches and historical pull requests are read-only artifacts:
fetching them does not authorize switching to them, creating more, opening
PRs, or publishing to them. Do not delete them as a side effect of this
policy. Direct `main` work is required even when a tool defaults to making
a PR. If a tool or repository rule forbids direct `main` publication,
report `BLOCKED`; never work around it by creating another branch/PR.

Before beginning a new change or publishing evidence:

1. require a clean local `main`;
2. `git fetch origin`;
3. require local `HEAD` to equal `origin/main` before editing, or
   fast-forward to it;
4. check the canonical remote head used by repository policy;
5. never force-push or overwrite concurrent work.

After every completed commit, push directly to `origin/main` and verify the
local and remote commit IDs are identical. After a long-running test, fetch
again before committing/publishing. If `origin/main` advanced while an
**unpublished** local commit exists, reconcile that unpublished work onto the
new remote head without rewriting published history, rerun affected checks, and
then push normally. Do not leave completed work only locally between milestones.
Use a non-force fast-forward to the *current* `origin/main`; never push to a
separate head ref. If concurrent changes or local edits prevent immediate
sync, preserve unpublished work on the existing local `main` and reconcile it
without creating a branch, PR or extra worktree. Verify that local and remote
main identify the same commit after every successful publication.

This exact synchronization is required so another project manager can inspect
the same current state remotely at any time.

## Documentation working-set contract

Documentation must guide decisions continuously without consuming the model
context.

The model context is 256K tokens. Keep documentation at or below **25% of the
context (64K tokens)**. The always-loaded working set should normally be much
smaller, targeting **24K tokens or less**, leaving room for targeted reference
sections.

Always keep these compact documents in working context:

1. this file, `docs/AGENT_CONTEXT.md`;
2. `docs/VISION.md`;
3. `docs/README.md`.

For every decision, use their current contents, not remembered older wording.
After any pull that changes one of them, reload it before continuing.

The following are authoritative long references but must be retrieved by
relevant heading/line range rather than loaded wholesale:

- `docs/ROADMAP.md` — active priority/evidence rows and deployment state;
- `docs/coding_standards.md` — invariants for the code being changed;
- `docs/testing_standards.md` — qualification contract for the test being run;
- `docs/context.md` — Linux/MM/swap technical background;
- `docs/benchmark.md` and `docs/compile.md` — when applicable.

When a long document accumulates completed experiment narrative, compact its
active rule/decision and let Git history and committed evidence preserve the
transcript. Do not duplicate the same policy across multiple long documents.
Both Codex and project-manager edits must update documentation when behavior,
scope, target identity, acceptance criteria, or evidence changes.

## Production-readiness definition

The mission has three separately reported outcomes.

### CODE_PRODUCTION_READY=PASS

Require all of the following for the exact source:

- required source/native/W=1/W=2 and exact-host `make test_full` RAM/integration
  PASS, plus `make test` real-physical algorithm PASS once its trusted admission
  protocol exists; the current physical-INCOMPLETE algorithm tier cannot
  satisfy this production-ready gate;
- required GitHub CI PASS on current `main`;
- real Linux anonymous-page swap-out and swap-in through swapz PASS;
- full authorized-card backing geometry and maximum safe logical capacity
  verified with incompressible content;
- sustained high-occupancy GC/churn demonstrates forward progress and byte-exact
  recovery without target failure;
- DISCARD/TRIM, overwrite, flush/FUA, suspend/drain and normal teardown preserve
  ownership/order/integrity;
- CPU and metadata RAM remain bounded at production capacity;
- no unresolved critical correctness, ownership, use-after-free, race,
  capacity-exhaustion or lifecycle defect.

### DEPLOYMENT_PRODUCTION_READY=PASS

Require all of the following:

- qualified artifacts are installed with verifiable provenance;
- persistent startup/shutdown configuration identifies only the authorized SD
  card and never substitutes another device;
- a fresh boot creates a **fresh empty volatile mapping**, never reconstructs
  previous-boot swap pages, and refuses hibernation use;
- missing/ambiguous card or failed initialization yields a clear no-swap state;
- normal shutdown/reboot path uses ordinary swap deactivation and never
  force-removes active mappings;
- upgrade, uninstall and monitoring behavior are defined and exercised as far
  as possible without rebooting;
- an automatic persistent cold-boot acceptance harness is installed and armed.

### Cold-boot observation

Codex must not reboot the computer. It can still finish code/deployment
production readiness by proving the boot logic with non-reboot checks and
arming the acceptance harness.

When both production-ready outcomes above pass and the harness is armed, report:

- `PRODUCTION_READY_FOR_OWNER_REBOOT=PASS`
- `COLD_BOOT_HARNESS=ARMED`
- `COLD_BOOT_OBSERVED=NO`

After an owner-initiated reboot, the harness must persistently record boot ID,
kernel release, installed source/artifact identity, target parent/partition
identity, mapper UUID/table/capacity, `/proc/swaps`, priority, swapz status,
service state and relevant kernel errors. Only that evidence may change
`COLD_BOOT_OBSERVED` to `PASS` or `FAIL`.

Cold-boot observation is not a prerequisite for Codex to finish the **code**
production-readiness mission because Codex is explicitly forbidden to reboot.

The cold-boot verifier is integrated into the owned package and official
rootless contract path. `package-dkms.sh` installs
`$prefix/sbin/swapz-primary-boot-verify` mode 0755 and
`swapz-primary-boot-verify.service` mode 0644 with the installed sbin path,
covers both in package ownership/hash and uninstall checks, and still leaves
the primary swap and verifier disabled; installation never uses `--now`.
The isolated `tests/runtime/native/systemd/swapz-primary-systemd-test.py`
fixture is executed by the official rootless stage. After the
execution/physical qualification gates pass and any selected-partition raw-swap
configuration is removed, the owner-side activation flow must confirm the
passive `dev-mapper-swapz\\x2dprimary.swap` unit is disabled (including any
legacy wants symlink), run `swapz-primary-boot-verify arm`, and enable
`swapz-primary-mapper.service` plus `swapz-primary-boot-verify.service` for
the next boot without starting them in the arming boot. The owner alone
initiates reboot. Installer/test-runner integration is implemented;
qualification, arming and owner reboot remain open.

## Current decision order

Unless evidence changes the order, work on:

1. **Target/configuration abstraction — implemented.** The manager, package
   and systemd generator use a protected PARTUUID selector; target path,
   major:minor and capacity are discovered at runtime. Alternate synthetic
   identities and geometries are covered in direct-C tests. The prepared
   start/stop/recovery coordinator, bounded status emission, portable
   little-endian delta64 semantics, deliberately unaligned codec coverage,
   authority geometry/generation checks, drain-wakeup closure, GC
   failure-recovery/high-occupancy coverage and hardened standalone physical
   formatter identity are implemented. Do not pin a moving `main` SHA or CI
   result in this always-loaded decision list: determine current source and CI
   from Git/GitHub and determine owner qualification from the canonical
   `test_results.json`. An older PASS never qualifies a newer source.
   [docs/handoff/production-readiness.json](handoff/production-readiness.json)
   is historical unless it explicitly carries a current source-bound release
   evidence set. The production lifecycle remains runtime-disabled until the exact
   current source and card-specific acceptance gates pass and the owner arms
   the cold-boot harness. The same qualified artifact is unlocked only by a
   volatile source/boot/PARTUUID/size-bound preflight token. The historical
   fixed-device live-swap supervisor is not the active selector or deployment
   path.
2. **Active:** directly qualify interruption and recovery behavior for the
   primary lifecycle coordinator. Prepared start, normal stop and standalone
   recovery are wired behind boot-scoped runtime execution authorization. They
   bind each operation to the run manifest, exact target header and recorded
   module ownership. Rootless deterministic interruption coverage now enumerates
   every durable STARTING/STOPPING/RECOVERING cleanup boundary plus
   RECOVERY_REQUIRED and RESTORED, requires exact-owned convergence, and proves
   wrong mapper identity cannot trigger swapoff/remove. Remaining lifecycle
   evidence is owned-`null_blk` execution and native-process interruption
   behavior. A noninstalled test-only build seam now exists for that work: ordinary production is compiled capable but remains runtime-locked without a
   current-boot authorization, while the owned-null_blk macro retains isolated
   private selector/recovery/qualification authority. The public Makefile never selects that seam. The latest source
   also permits unrelated swap entries such as
   `/swapfile` while rejecting an active or ambiguous alias of the selected
   target. Admission now scans every visible PID's mountinfo for the selected
   partition and its physical parent, recognizes swapfiles by filesystem
   `st_dev`, and rejects unknown or type-inconsistent `/proc/swaps` rows. Start
   repeats the mount, physical-parent and active-swap checks after opening its
   exclusive backing descriptor and immediately before mapper creation. Block
   zero remains read-only throughout the lifecycle.
   Focused production-C mount/swap inventory regressions pass; exact-source
   owner qualification remains pending. Do not arm production runtime
   authorization before exact-source and card-specific acceptance gates pass.
3. actual Linux swap correctness on the authorized card;
4. maximum safe full-card capacity and bounded metadata RAM. The authority
   policy for the current `/dev/sda1` geometry admits 27,080,192 logical pages,
   retains 3,385,024 GC-reserve blocks plus one independent 256-block foreground
   COW segment, exposes 110,920,466,432 mapper bytes and 110,920,462,336
   Linux-usable swap bytes. The 17 source-derived capacity-index arrays total
   884,391,736 bytes (843.4217 MiB): 28 bytes per logical page for the
   20-byte map plus two 32-bit segment-membership links, 4 bytes per physical
   block for live-record, extent-class and sequence-delta indexes, and 36
   bytes per segment for GC/accounting, page-list, trim/role and sequence-base
   sidecars. Independently rounding each array to 4KiB allocation pages yields
   884,436,992 bytes. The largest single array is the 541,603,840-byte mapping
   table. Against the frozen 1.25GiB metadata-and-target peak limit,
   page-rounded capacity-index arrays leave 457,740,288 bytes (436.54 MiB) for
   fixed target allocations and runtime overhead; this is arithmetic headroom,
   not a measured fit. These figures exclude fixed target scratch, caches,
   workspaces, vmalloc metadata, page tables and allocator implementation
   overhead. They are not proof that a full-capacity live target fits available
   RAM; measure actual allocation and peak memory before advertising or
   activating that capacity. The kernel authority preflight and primary
   userspace mapper sizing now enforce the same one-segment foreground-COW
   headroom rule; rootless policy regression covers both the 16 GiB fixture and
   current-card geometry. Recalculate from the runtime-selected geometry if the
   protected PARTUUID changes; these host-specific figures are not production
   capacity constants. Full-capacity loaded-host memory and physical RAW/GC
   qualification remain open.
5. sustained occupancy/GC/churn and physical service;
6. persistent startup/shutdown integration and cold-boot acceptance harness:
   bounded fail-closed units, packaged verifier and rootless runner are wired;
   full qualification, owner-side arming and owner reboot remain open;
7. performance optimization only after correctness/lifecycle gates are closed.

At each milestone report exact `main` SHA, code/doc changes, tests, CI, current
card/swap state, capacity, unresolved risks and the next highest-value action.
