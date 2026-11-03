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
cover the selected target. The installed systemd generator now derives the
selected `.device` and by-PARTUUID `.swap` dependency names from the protected
selector; it adds device ordering and a conflict against that selector's
by-PARTUUID swap unit without embedding this host's path, device number or
capacity. The generator does not activate units, and the static primary units
remain disabled with manual start/stop refused until the full lifecycle and
boot path are qualified. A deployment that enables them must also ensure the
raw selected partition is not separately enabled as swap under a by-UUID or
other alias; the PARTUUID dependency alone cannot identify every alias.

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

## Current decision order

Unless evidence changes the order, work on:

1. **Target/configuration abstraction — implemented.** The manager, package
   and systemd generator use a protected PARTUUID selector; target path,
   major:minor and capacity are discovered at runtime. Alternate synthetic
   identities and geometries are covered in direct-C tests, and both required
   GitHub workflows pass on `6ebf6fd3c9a641c4fbf57c021ee0b9aad5b24efb`.
   Keep the privileged lifecycle disabled until separately qualified. The
   historical fixed-device live-swap supervisor is not the active selector or
   deployment path.
2. **Active:** native production lifecycle and standing-authorization policy
   cleanup;
3. actual Linux swap correctness on the authorized card;
4. maximum safe full-card capacity and bounded metadata RAM. The current
   `/dev/sda1` geometry admits 27,080,448 logical pages; a 16-byte map plus
   compact per-extent sequence index reduces the source-derived capacity-index
   lower bound from the 20-byte-map estimate of 813.92 MiB to 740.12 MiB
   (73.80 MiB saved net of the sequence index). This estimate excludes fixed
   target scratch, caches, workspaces and allocator overhead. It is not proof
   that a full-capacity live target fits available RAM; measure actual
   allocation and peak memory before advertising or activating that capacity.
   Recalculate from the runtime-selected geometry if the protected PARTUUID
   changes; these host-specific figures are not production capacity constants.
5. sustained occupancy/GC/churn and physical service;
6. persistent startup/shutdown integration and cold-boot acceptance harness;
7. performance optimization only after correctness/lifecycle gates are closed.

At each milestone report exact `main` SHA, code/doc changes, tests, CI, current
card/swap state, capacity, unresolved risks and the next highest-value action.
