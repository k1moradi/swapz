# Retained Lubuntu trial: ownership and recovery audit

**Scope:** Agent 3, source `main` at `e941dfe48fca62cf0fffe4abbfb4d117b2ffb328` (2026-11-14). **Decision: BLOCKED for new `swapzctl` lifecycle authority.** This audit is read-only design and rootless-test evidence, **not** evidence that the Lubuntu device has been inspected, drained, or qualified. No physical operation, installed-command change, CLI edit, mapper removal, or new cleanup entry point is authorized here.

The existing private path is `tests/tools/physical-swap-probe.py`; the public selector `tests/tools/algorithm-physical.py::_recover_pending_algorithm_trial` launches its `recover-pending` action with `sudo -n` and preserves an unresolved-recovery refusal. The existing helper's `recover_pending_algorithm_trial()` is a narrowly scoped same-boot *development real-swap* reconciliation path. Do not implement a second independent controller or infer owner identity from a `swapz-demo-physical-*` prefix.

## Source trace and recorded authority

| Source anchor | What it actually establishes / does not establish |
| --- | --- |
| `ALGORITHM_RUNTIME_BASE`, `_algorithm_runtime_base` (physical helper ~126-133, 1668-1705) | Root-controlled `/run/swapz/algorithm-physical` with 0700 directories and tmpfs check; no persistent on-disk swap metadata. **No explicit kernel boot ID is saved or validated in the helper.** Same-boot relies on the volatile `/run` placement and root namespace trust. |
| `_select_run_directory`, `_state_run_directory` (~1738-1770) | Derived `swapz-physical-<32 hex>` direct child, not a client-supplied mapper name. Legacy `/var/lib/swapz/physical-recovery` is inspection/manual-reconciliation only, never automatic block-zero restoration. |
| `_partition_lock`, `_burn_review`, `_consume_review` (~1771-1854) | Nonblocking `flock` on `partition-<PARTUUID>.lock`; one-use consumed marker; exclusive, fsynced `partition-<PARTUUID>.active` containing exact `run_id`, PARTUUID, major and minor. The marker remains until verified COMPLETE. Lock ownership is per process, not a long-lived user identity. |
| `_prepare_state`, `_save_state`, `_save_results` (~1944-1966, 1999-2019, 3592-3662) | Run-owned `state.json` and `results.json` (0600) via temp write, file fsync, atomic replace, directory fsync. State binds confirmed by-PARTUUID/by-UUID selector, canonical device, major/minor, PARTUUID, byte size, parent major:minor/model/transport/size/removability/card-identity digest, immutable first-page hash, logical geometry, source commit, helper Git SHA and SHA-256, mode/scope, swap-before-run policy, module ownership, mapper name and UUID token, and phase. Result-record bindings are separately checked. |
| `_validate_owned_mapper_identity`, `_mapper_exists`, `_verify_owned_mapper` (~2823-2887, 3064-3082) | Exact matching name/UUID suffix, one name/UUID inventory pairing; then current DM info major:minor, `/dev/mapper` block identity, sysfs DM name/UUID/size, one lower slave, and exact target table (accepting lower path or major:minor notation). A name, UUID, table or DM dev number alone is **not** evidence of durable mapper incarnation or exclusive lifecycle authority. |
| `inspect_target_identity_for_recovery` (~3518-3591) | Reopen saved canonical partition and recheck block identity, size, PARTUUID, parent and, when recorded, card fingerprint and lower counter binding. It does **not** resolve an arbitrary current device matching a remembered name. |
| `_active_swap_for`, `_prepare_owned_mapper_removal` (~2583-2606, 3664-3708) | Parse Linux `/proc/swaps` and resolve block identities; invoke **only owned mapper** `swapoff -- <mapper>` if active; require fresh inactive observation; settle udev; reprove mapper identity and swap inactivity. Failure/ENOMEM/timeout retains the mapper, and no force removal is attempted. `/proc/swaps` and path resolution are observations, not independent cross-namespace drain proofs. |
| `recover`, `_release_partition_ownership` (~1855-1910, 3234-3450) | Authenticate state/results/active owner marker under partition lock, current partition, saved mapping and module ownership; remove mapper only after its own protected checks; conditionally unload owned module; recheck header and original raw-swap restoration policy; sample final observations; publish COMPLETE then release owner marker. Recovery never restores SWAPSPACE2 block zero. |
| `recover_pending_algorithm_trial`, `main` (~3451-3516, 5969-6060) | Accept zero or exactly one trusted marker, reject ambiguous journal/scope/selector, then call `recover` with the **original** identical selector twice. Root-only existing private `recover-pending` has no arbitrary mapper argument. Its success means the helper's reconciliation completed, **not** that a new `swapzctl` delegate is qualified. |

The initial `swap_was_active`/original swap size, used KiB and priority are recorded from the selected partition's Linux swap inventory. An originally active raw partition may have live pages: its `swapoff` must complete before lower data access; original policy is restored at the end. Development runs originally inactive leave it inactive. Unrelated swapfiles remain independently Linux-owned in current development mode (`unrelated_swapfiles_deactivated_by_run=False`). Running swapz mapper activation is recorded in the real-swap oracle and, if intentionally retained, in the `KEPT_ACTIVE` state/results with priority 32767. Those samples **do not** serve as authority to stop it outside the original helper.

### Transaction and interruption boundaries

| Boundary / crash moment | Safe reconciliation rule |
| --- | --- |
| `plan` / source and target preflight, before one-use burn | Read-only. No cleanup authority acquired. Refuse if original target/parent is uncertain. |
| Consumed record fsync, state directory creation, PREPARED state/result saves; interruption before `.active` marker fsync | Review stays consumed; no authenticated active claim. **BLOCK automatic adoption**. Inspect incomplete record read-only. |
| Active marker create/write/fsync and directory fsync, before raw `swapoff` | Recovery can be attempted only by the original helper after exact marker+state+results validation and partition `flock`. An interrupted `swapoff` is an unknown Linux state: resample and never assume success. |
| `swapoff` returns or is interrupted, before `SWAP_OFF`/`EXISTING_SWAP_READY` state fsync | Only fresh source-owned partition/mapper checks can distinguish raw active, raw inactive and partial drain. If swapoff failed or is ambiguous, do not open lower data area. No forced retry on an unknown target. |
| `MODULE_PENDING` fsync, `insmod`, `MODULE_OWNED` fsync | Module creation between pending and owned publication is ambiguous. The helper refuses a loaded module whose saved ownership is not MODULE_OWNED. Do not unload on guesswork. |
| `dmsetup create`, `udevadm settle`, `MAPPED` fsync, mapper-only `mkswap`, Linux `swapon` | A mapper may exist before stage publication. Match original DM name **and** UUID, table, lower slave and identity; treat missing/mismatched data as BLOCKED. Never format the protected raw partition. A terminated `swapon` needs a new current Linux swap inventory, not a success assumption. |
| Oracle writes / `ORACLE_PASS` and results fsync | Positive test results do not imply drained swap. The normal cleanup path remains necessary. An intermediate result-record phase can lag the state; immutable bindings must still agree. |
| `KEPT_ACTIVE` state fsync then result fsync | Explicit retained trial; mapper may have live Linux swap pages. Only original `recover-pending` may attempt normal `swapoff` with bounded headroom and drain validation. ENOMEM, failed `swapoff`, competing holder, or incomplete evidence => retain mapper and marker. |
| `swapoff` success, udev settle, `dmsetup remove`, module unload, state fsync, original swap `swapon` / final observation | Re-check at each mutation boundary; do not infer an absent mapper means ownership of a loaded module. A crash between `dmsetup remove` and state fsync can make module provenance unprovable; current helper fails closed. Interrupted raw `swapon` must be verified against original size and priority policy. |
| COMPLETE state fsync, active-marker unlink + directory fsync, result fsync | Only exact verified final state permits ownership release. **Known gap:** if killed after COMPLETE state save but before marker unlink, `recover()` rejects COMPLETE on reentry; manual read-only reconciliation may be required. A failed directory fsync attempts to restore the marker but remains uncertain; no extra mutating observation after release. |

`_save_state`/`_save_results` fsync file before replace, then sync directory; neither makes a multi-file transaction atomic. An interrupted or failed `fsync`, `os.replace`, `os.unlink`, or partial record update must remain **uncertain**, even if a later path read looks plausible. The active marker and the immutable two-record binding are therefore separate mandatory checks, not optional conveniences.

## Threat model and unresolved delegation gates

- **Namespace/path substitution:** symlink/hardlink, rename, bind/overmount of `/run`, `/dev`, `/sys`, `/proc/swaps`, or a replaced by-PARTUUID alias can change the object reached after earlier checks. The helper checks modes, lstat, selected block identity and mapper relationships, but the journal file reads use path-based `read_bytes` after `lstat` and the DM identity check is not an atomic kernel snapshot with the later remove syscall. A separate process cannot elevate those observations to a proof. An untrusted mount namespace must be rejected by a future controlled API.
- **Boot/session:** volatile tmpfs is a same-boot assumption, not an independently verified boot-ID binding. A copied marker, new mount namespace or stale/malformed run identity must not be automatically adopted. An explicit boot-id and kernel/module artifact continuity check is a proposed hardening task; the existing code does not assert it.
- **Collision/recreation:** an attacker or concurrent privileged actor can replace the name, UUID or mapper incarnation between observations. Existing exact table/sysfs/slave checks help but do not pin identity through `dmsetup remove`; no new `swapzctl` stop authority is justified. Unexpected holders or a second owner must BLOCK, not be killed or forced off.
- **Linux-owned state changes:** independent raw `swapon`, third-party `swapoff`, altered swapfile priority, hidden `/proc/swaps`, or a partially completed `swapon`/`swapoff` must be treated as competing/unknown state. `Used=0`, absent `/proc/swaps` row and successful `swapoff` return are not sufficient independent drain/ownership proofs; failed `swapoff` (including ENOMEM) preserves live pages.
- **Torn/corrupt journal and source drift:** duplicate JSON keys, missing/changed helper hash, results/state binding mismatch, altered parent fingerprint, damaged marker, failed durable publication, lost RAM mapping authority or stale module evidence all require refusal and read-only inspection. Reboot cannot recover volatile compressed page mappings and must never be marketed as crash-safe resume.
- **Privileged delegation:** `recover-pending` already exists as a root-only private operator action. A new `swapzctl` command must not shell out based on a mapper name, accept a path from an untrusted user or use its own swapoff/removal logic. Before any public delegation, an integration owner must specify an authenticated one-way request protocol pinned to the original helper/source, protected mount namespace, exact run/boot identity, owner lock, immutable journal and current kernel object identity, with independently audited post-checks and a clear zero/one/multiple-marker result. No such API is implemented in this assignment.

## Decision matrix

| Requested operation | Decision | Reason |
| --- | --- | --- |
| Existing `swapzctl status/list/inspect/health/diagnose` | **SAFE READ-ONLY** within their documented bounded observer limits | Not a swap-off or ownership grant; cannot infer current exact journal authority. |
| Separate root-only **read-only** inspection of validated `/run` journal | **FEASIBLE DESIGN, NOT SHIPPED** | Require anchored non-following directory descriptors, exact ownership/modes, bounded strict JSON, stable two-record/marker sampling, and explicit UNKNOWN on a race. No secrets/run token emitted. |
| Existing private helper `recover-pending` against exact same-boot development record | **EXISTING CONDITIONAL DELEGATE** | Helper itself decides under its original checks; no arbitrary name adoption; may refuse as RECOVERY_REQUIRED. Not endorsed as an automatic `swapzctl` action. |
| New `swapzctl stop/recover <mapper>` or automatic invoke of private helper | **BLOCKED / NOT IMPLEMENTED** | Cross-process identity, namespace, boot-id, journal publication and DM substitution concerns require separate audit and qualification. |
| Generic `swapoff`/`dmsetup remove`/`rmmod`/`mkswap` of guessed targets | **FORBIDDEN** | Risks live swapped pages and raw header or unrelated device; lacks helper-owned proof. |
| Physical or production deployment qualification | **NOT PERFORMED** | Rootless fixtures are purely adversarial models. A loaded/physical and independent review gate remains. |

## Reproducible, non-destructive checks

Run from the repository root: `python3 -B tests/runtime/native/userspace/swapzctl-trial-ownership-test.py -v`. The fixture imports the real helper but replaces all privileged operations with injected fake run records, `recover`, Device Mapper inventory and `swapoff`/`udevadm` command responses. It exercises zero/multiple/ambiguous markers, symlinks, state/marker mismatch, helper-only delegation, failed/incomplete recovery, immutable source/mapper bindings, collision, ENOMEM and post-settle substitution. **This is no privilege/physical qualification.** No CLI, kernel path, production manager, or disk is modified.

### Review blockers for a future integration owner

1. Authenticate current namespace, actual boot identity, original helper and module binary identity, and exact stable mapper incarnation through the final mutating syscall, not just a timestamped sample.
2. Define an anchored fd-based, no-symlink, non-following read-only journal accessor that cannot change ownership; keep state/results/marker validation atomic enough to return UNKNOWN on rename or concurrent writer.
3. Resolve the `COMPLETE`+retained-marker interruption window and verify no early module unload/removal after swapoff failures, external activation or unexpected holders.
4. Independent security review, CI/rootless adversarial evidence and exact-source loaded and physical qualification before Agent 1 or integration owner adds public lifecycle control.
## Follow-up durability and custody review (source unchanged, 2026-11-14)

The rootless Agent 3 fixture now also checks duplicate marker/state JSON keys,
hardlinked or world-readable marker substitution, state-directory refusal,
pre-replace file fsync/rename failures, post-replace directory fsync uncertainty,
non-COMPLETE release refusal, and both owner-marker restoration outcomes after
release-directory fsync failure. It verifies exact-identity duplicate DM
inventory rejection. Each fake is scoped to a temporary directory; no real
Device Mapper, Linux swap, or privileged operation is performed.

**Verified source-level distinction:** `_save_state` performs file fsync
before `os.replace`, then a directory fsync. A failing *pre-replace* sync
must leave the old published record visible. A failing *post-replace* directory
sync may leave the replacement visible, but that observation is not a durable
commit and cannot authorize cleanup. `_release_partition_ownership`
attempts re-creating the original marker after an uncertain directory sync;
if recreation fails, it explicitly reports `owner_marker=uncertain`. No
reader may interpret marker absence in this window as authorization.

**Unresolved P0 issues in the private helper (no code change in this audit):**

1. `recover()` refuses a journal whose saved `stage` is already `COMPLETE`.
   A crash between `COMPLETE` publication and active-marker release leaves
   an owned marker that `recover-pending` cannot reconcile automatically.
   A dedicated *post-COMPLETE read-only verification and conditional marker
   release* transaction is required; repeating mapper removal is not.
2. `recover_pending_algorithm_trial()` observes marker metadata with
   `lstat()`, then opens content through `read_bytes()` by path. The
   underlying `recover()` also reopens saved records and mapper paths.
   Those reads are not a pinned inode/mount transaction. Ownership remains
   unproven under privileged concurrent rename/overmount substitution.
3. Results/state bind recorded `helper_sha256` and module provenance
   *to each other*; `recover()` does not independently authenticate the
   currently executing helper file or loaded module bytes against those
   records. The verified DM name/UUID/table is not an unforgeable mapper
   incarnation token.
4. The fixture was **initially standalone** and was not executed by the
   older native CI runs. Its later integration into `tests/suites/Makefile
   test-userspace` runs these mocked cases on subsequent exact-source CI;
   historical results cannot be retroactively relabeled. The rootless
   suite does not authenticate real owner journals or validate live swap.

No automatic `swapzctl` delegation is justified by these tests. The existing
private helper's own recovery is still the sole conditional recovery path,
and physical/loaded qualification remains separate.

## Agent 3 follow-up: completed-stage and provenance checks (2026-11-14)

The integrated rootless fixture now exercises the original helper through
recover_pending_algorithm_trial() when the saved state is COMPLETE but an
active owner marker is retained. This must return RecoveryRequiredError
without a privileged operation. A simulated interrupted delegate must also
preserve the marker. Source/helper hashes, header fingerprint, mapper
name/UUID and parent/partition identity are cross-checked between the
saved state and results; the fixture asserts mismatch refusal.

This is **fail-closed regression evidence, not a fix for the recovery gap**.
Recovery at COMPLETE still needs an independently reviewed, same-boot
read-only verification under the original partition lock, followed by
conditional marker release only when original swap policy, mapper/module
absence, immutable header and exact partition/parent identity all hold.
Do not replay swapoff, remove a mapper or unload a module from COMPLETE.
A cross-file consistency match does not authenticate the executable or
current kernel module against the recorded hashes.
