# Agent operating context

This is the compact, **always-loaded** operating contract for engineers and
agents working on swapz. It is the first document to read after every fetch of
`main`, after any documentation change, and before a destructive host action or
major architecture decision. Longer documents remain authoritative references,
but retrieve only the sections needed for the current decision.

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
and kernel swapoff grace. The mapper service requires the persistent recovery
mount and runs `preflight -> recover -> prepare -> start`. It deliberately does
not `BindsTo` removable media. `swapzctl primary start` already performs
`swapon` and `primary stop` performs `swapoff` and safe owned mapper teardown.
Therefore the mapper service alone is WantedBy=swap.target and MUST be enabled
only after qualification; the `.swap` unit is a passive view of the active
swap and MUST NOT be enabled or started independently. For shutdown/reboot,
the mapper's normal stop precedes the observed `.swap` stop, so the manager
remains the only swapoff owner. Clear any legacy enabled `.swap` wants symlink
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
report filesystem shared with the manager's qualified recovery storage,
physically separate from the SD card. On the next boot, the verifier checks
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
identity. Formatting or repartitioning may intentionally replace UUID/PARTUUID;
record the controlled identity transition before continuing. Never substitute
whatever later happens to be named `/dev/sda` or `/dev/sda1`.

The entire positively identified SD card and its sole partition are disposable
development media. Existing card contents need no backup. The owner grants
standing authority to repartition, format, overwrite, DISCARD/TRIM, benchmark,
and repeatedly reinitialize that card when useful to the mission. No other
physical disk, partition, filesystem, mapper, or swap area is in destructive
scope.

Use the whole authorized partition as physical backing and expose the largest
logical swap capacity that remains correct for incompressible data, SWZ metadata,
alignment, GC reserve and forward-progress reserve. Do not advertise capacity
that depends on favorable compression.

## Standing owner authorization

The owner decision recorded on 2026-11-03 replaces repeated per-run owner or
external-review permission requests for physical work on this **current
dedicated SD-card target**. Agents may autonomously use sudo, format the card,
create/remove verified swapz mappings, run swapoff/swapon for the verified
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
immutable evidence for the older computer. Their approval mechanics are not the
current authorization model and must not block work on the dedicated
`/dev/sda1` card.

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
- freely destroy/reinitialize the authorized SD card instead of preserving
  irrelevant historical card contents;
- remove obsolete approval gates and recovery complexity that exist only for
  the older shared-swap experiment, while retaining technical safety gates;
- reuse valid evidence instead of rerunning expensive qualification without a
  reason;
- use `make fast_test` for development decisions and `make test` for exact
  source qualification;
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

There is one development branch: `main`.

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

- required source/native/W=1/W=2 and exact-host `make test` qualification PASS;
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
   identities and geometries are covered in direct-C tests. Current production
   source `a31661f887f1fa7a88efdfff5186a84672217950` includes the prepared
   start/stop/recovery coordinator, bounded status emission, portable
   little-endian delta64 semantics, deliberately unaligned codec coverage,
   authority geometry/generation checks, drain-wakeup closure and GC
   failure-recovery/high-occupancy coverage, and hardened standalone physical
   formatter identity. Current `main`
   `a31661f887f1fa7a88efdfff5186a84672217950` passed production-C CI run
   `41655643592` and native project-goal CI run `41655643668`. The latest
   full owner `make test` passed on older source
   `acdeba452aa142c702bed40010c083276a692711` and published report commit
   `17ed3c639ce99708ee2bfbed7d979b35592c7a5a`; exact-current-source owner
   qualification remains open. That run passed ID36 after the owner freed host
   memory by closing programs. See the compact snapshot at
   [docs/handoff/production-readiness.json](handoff/production-readiness.json).
   The primary plan remains BLOCKED and the privileged lifecycle stays disabled.
   The historical fixed-device live-swap supervisor is not the active selector
   or deployment path.
2. **Active:** directly qualify interruption and recovery behavior for the
   primary lifecycle coordinator. Prepared start, normal stop and standalone
   recovery are now wired behind the existing disabled execution gate. They
   bind each operation to the run manifest, exact target header and recorded
   module ownership. Rootless deterministic interruption coverage now enumerates
   every durable STARTING/STOPPING/RECOVERING cleanup boundary plus
   RECOVERY_REQUIRED and RESTORED, requires exact-owned convergence, and proves
   wrong mapper identity cannot trigger swapoff/remove. Remaining lifecycle
   evidence is owned-`null_blk` execution and native-process interruption
   behavior. A noninstalled test-only build seam now exists for that work: the
   production gate remains literal zero, while the owned-null_blk macro requires
   private selector/recovery/qualification paths before it can compile with the
   gate enabled. The public Makefile never selects that seam. The latest source
   also permits unrelated swap entries such as
   `/swapfile` while rejecting an active or ambiguous alias of the selected
   target. Do not enable the gate before exact-source and card-specific
   acceptance gates pass.
3. actual Linux swap correctness on the authorized card;
4. maximum safe full-card capacity and bounded metadata RAM. The current
   `/dev/sda1` geometry admits 27,080,448 logical pages; a 16-byte map plus
   compact per-extent sequence index reduces the source-derived capacity-index
   lower bound from the 20-byte-map estimate of 813.92 MiB to 776,077,112 bytes
   (740.1248 MiB, 73.80 MiB saved net of the sequence index). Independently
   rounding each current array to 4KiB allocation pages yields 776,118,272
   bytes; the largest single array is the 433,287,168-byte mapping table. These
   figures exclude fixed target scratch, caches, workspaces, vmalloc metadata,
   page tables and allocator implementation overhead. They are not proof
   that a full-capacity live target fits available RAM; measure actual
   allocation and peak memory before advertising or activating that capacity.
   Recalculate from the runtime-selected geometry if the protected PARTUUID
   changes; these host-specific figures are not production capacity constants.
5. sustained occupancy/GC/churn and physical service;
6. persistent startup/shutdown integration and cold-boot acceptance harness:
   bounded fail-closed units, packaged verifier and rootless runner are wired;
   full qualification, owner-side arming and owner reboot remain open;
7. performance optimization only after correctness/lifecycle gates are closed.

At each milestone report exact `main` SHA, code/doc changes, tests, CI, current
card/swap state, capacity, unresolved risks and the next highest-value action.
