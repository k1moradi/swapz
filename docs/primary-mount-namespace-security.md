# Primary manager mount-namespace admission contract (issue #94)

**Status: blocking until production passes.** This contract is independent of
any copied formatter parser. The executable fixture
`tests/runtime/native/userspace/swapz-primary-mount-namespace.c` includes the
*production* `src/userspace/swapz-primary.c` without defining
`SWAPZ_PRIMARY_ROOTLESS_TEST` (that test mode disables the real readers). The
fixture is a checkpoint behavior test, not an architectural requirement that
cross-PID scanning live inside `swapz_primary_read_mount_facts()`. The
architecture-neutral source guard in
`tests/runtime/native/primary-lifecycle-audit-test.py` discovers production
cross-PID scan paths by behavior rather than by function name and requires the
coordinator to reach a path with the corrected namespace-exit classification at
the final safe pre-mutation boundary.

## Source boundary and independent checks

The selected partition is identified by its verified `dev_t` (for the rootless
fixture, `8:1`); its physical parent must be independently resolved and compared
as exact `dev_t` (`8:0`). Never equate an unrelated `8:2` sibling with the
selected partition, and never infer block identity from a `/dev/sd*` string.
The current process's `/` mount `dev_t` is an independently retained root
safety fact. A different PID's root must not replace it.

Before any primary prepare, start, restoration write, Device Mapper mutation,
`mkswap`, or swapon operation that can change the selected storage, scan the
current mount table **and every visible numeric `/proc/<pid>/mountinfo`** for
both selected partition and parent. A match is busy and must refuse admission.
No target mount in `/proc/self/mountinfo` is insufficient evidence. A missing,
malformed, truncated, unreadable, or partially read inventory is not a clear
inventory. The `/proc` directory itself being inaccessible is a refusal.
Repeated PID entries or PID churn do not justify replacing observed root facts.
A missing leader `/proc/<pid>/ns/mnt` marker is **not** proof that
`/proc/<pid>/task` has no surviving non-leader threads: where the task
inventory remains visible, inspect it or refuse admission as BLOCKED. This
remains true if the marker disappears between the initial and confirming
namespace stats or after an unopened leader mountinfo exit error before its
follow-up namespace stat. The owned rootless fixture must cover those timing
windows with visible selected-partition and selected-parent workers. Either
a busy observation or fail-closed error is acceptable; a clean admission is
a regression failure. A missing leader marker with inaccessible task inventory
is ambiguity, not positive evidence of safe process exit.

For each PID with an **unopened leader** mountinfo table, errors `EINVAL`,
`ENOENT`, and `ESRCH` allow that leader table to be skipped only if a
follow-up stat of `/proc/<pid>/ns/mnt` proves the leader namespace marker
absent (`ENOENT` or `ESRCH`). That proof does **not** authorize skipping the
PID's task inventory; inspect visible non-leaders or refuse. If the leader
namespace exists, the stat fails for any other reason, or the mountinfo file
was opened before a parse/read/close error, refuse. An `EACCES`, `EPERM`,
`EIO`, or other unclassified inventory error always refuses. In particular,
`EINVAL` on mountinfo by itself is not a safe reason to skip a PID. Follow the
standalone formatter's corrected behavior, not its earlier permissive version.

On a successful inventory read, preserve the original root `dev_t` exactly and
keep these independent admission gates intact: active `/proc/swaps` entries
(including swapfiles whose filesystem backs the selected storage), Device Mapper
name/UUID and table ownership, selected/parent `holders` and `slaves`, and
source/parent topology. Unrelated host swapfiles need not be rejected solely
for existing. No mount scan substitutes for swap/DM/holder inspection.

## Root-filtered process inventories

A foreign process or non-leader task can retain the same mount-namespace
identity and numeric PID/start ticks while `chroot` restricts the mountinfo
rows available to the coordinator. The first production correction compared
`/proc/<pid>/root` before and after each mountinfo read. Independent audit
showed that was insufficient: a disposable rootless user/mount namespace with
only tmpfs reproduced **root ABA** where both observations were `/`, but the
mountinfo descriptor was opened during a temporary chroot and permanently
omitted the private mount. The PID/start ticks and mount namespace stayed the
same. No block device, mapper, format, mkswap or swapon operation was used.

Production therefore does not treat those root strings as completeness
evidence for a foreign view. After a syntactically valid mountinfo read and
namespace-identity revalidation, it pins the task's mount-namespace descriptor,
uses `statx(STATX_MNT_ID_UNIQUE)` on the task root only to seed a unique mount
ID, follows `statmount` parent IDs to the namespace-root mount, and enumerates
that pinned namespace directly with `listmount`/`statmount`. The selected
partition and physical parent are compared by exact kernel device numbers.
This namespace walk is independent of later PID/root reuse: a replacement root
in another namespace cannot resolve through the already pinned namespace, and
a different root inside the same namespace still walks to the same namespace
root.

The coordinator retains its ordinary mountinfo separately because that table
provides the current root-device safety fact. It must itself remain rooted at
`/`, and it completes the direct inventory for its own pinned namespace
before that full namespace can justify the same-namespace peer shortcut.
Leader disappearance still authorizes skipping only the leader table; visible
non-leader tasks retain their existing bounded scan and fail-closed rules.

The current foreign-namespace descriptor form of statmount/listmount requires
Linux 6.18 or newer. Missing syscall support, missing unique mount IDs,
namespace mismatch, an unreadable listed mount, malformed direct results,
descriptor-close failure or inventory overflow refuses admission. The focused
production-C regression keeps the process-root-filtered leader/task table
clean while the direct namespace seam contains a hidden selected or parent
device, and requires busy rather than clearance; an injected direct-inventory
error must remain BLOCKED.

This remains a repeated snapshot, not an atomic whole-host mount barrier. A
mount can arrive after the final namespace enumeration, and inaccessible PID
namespaces, detached references, stacked-filesystem aliases and physical
device-identity limits remain separate concerns. Those limits stay UNPROVEN;
this correction closes the reproduced stable chroot/root-ABA completeness
defect without claiming physical deployment acceptance.

## Final mutation boundary

The coordinator must repeat the cross-namespace mount admission **after all
intervening work that could race a mount** at the last safe boundary before
opening/writing a selected partition, changing a mapper, or activating swap.
It must recheck stable selected partition/parent and descriptor identity; retain
the same current-root identity, compare the target and parent against the newly
scanned tables, and refuse before *any* destructive side effect if the scan has
become busy or uncertain. A once-clean initial scan does not authorize a later
mutation. The lifecycle source guard is only a blocking structural regression:
it dynamically locates the cross-PID production scanner and requires a fresh
reachable scan after the exact target descriptor is opened and before the first
partition write. It does **not** qualify the no-side-effect behavior. Before
issue #94 can close, a rootless behavioral lifecycle regression must inject a
late mount change into the production mutation path and prove zero partition
writes/ioctls/swapon/DM mutation after that refusal.

## Rootless regression expectations

The native test uses regular temporary files and mocked procfs path resolution,
never `mount`, `unshare`, a block device, or a physical card. It executes
production mount-fact and swap-inventory functions directly. Its baseline root
is `259:0`; the other PID's root is `259:9` and must never change that
identity whenever production returns mount facts. Because this fixture does not
run a mutating lifecycle coordinator, it makes no claim that a pwrite sentinel
alone proves the required refusal-before-mutation contract.

| Synthetic observation | Expected result |
| --- | --- |
| Local root only; unrelated PID or sibling `8:2` | Admit; preserve root `259:0` |
| Selected partition `8:1` only in PID `3031` | Refuse |
| Selected parent `8:0` only in PID `3031` | Refuse |
| Local or other PID mountinfo malformed, empty or missing while namespace lives | Refuse |
| PID inventory or mountinfo permission denied | Refuse |
| Leader namespace marker absent while visible worker task holds selected partition or parent | Busy or BLOCKED; never admit from leader disappearance alone |
| Opened PID mountinfo has an I/O error | Refuse |
| `EINVAL`, `ENOENT`, `ESRCH` opening PID mountinfo, namespace still present | Refuse |
| Same errors opening a leader table, leader namespace marker proven absent | Skip only the leader table; inspect visible tasks or remain BLOCKED |
| Same errors opening a non-leader task table, that task namespace proven absent | Skip that vanished task if every remaining check is clean |
| Mountinfo missing while PID mount namespace remains | Refuse |
| Namespace stat itself permission denied or uncertain | Refuse |
| Active regular swapfile with filesystem `st_dev` equal to selected partition or parent | Refuse; unrelated swapfiles remain permitted |
| Active selected raw swap alias; matching DM ownership; nonempty holder directory | Independent refusal checks remain effective |
| Any refused admission | No destructive mutation; requires separate lifecycle-path proof |

The tests are deliberately red against the verified
`/proc/self/mountinfo`-only implementation and against a swap inventory that
ignores regular-file `st_dev`. Their failure is a useful P0 regression signal,
**not** a qualification PASS. Once the coordinator separates current-root facts
from a cross-PID scanner, the C behavior fixture must be wired to the actual
production admission boundary rather than keeping an obsolete dependency on
`swapz_primary_read_mount_facts()`. Publication of a test does not close issue
#94. A foreign task's mountinfo can also be filtered by its process root even with an unchanged namespace inode; successful namespace stats do not prove a full-root view. A prior harmless tmpfs/chroot observation does not prove destructive selected-storage admission. The remaining risks include hidden/inaccessible PID namespaces, detached
mount namespace FDs, stacked-filesystem aliases, cloned/reused device
identities, and time-of-check/time-of-use races; visible process scanning is not
an atomic, whole-host proof of physical device identity.
