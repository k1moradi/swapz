# Primary manager mount-namespace admission contract (issue #94)

**Status: blocking until production passes.** This contract is independent of
any copied formatter parser. The executable fixture is
`tests/runtime/native/userspace/swapz-primary-mount-namespace.c`, linked by
including the *production* `src/userspace/swapz-primary.c` without defining
`SWAPZ_PRIMARY_ROOTLESS_TEST` (that test mode disables the real reader).

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

For each PID with an **unopened** mountinfo table, errors `EINVAL`, `ENOENT`,
and `ESRCH` mean ordinary process-exit churn **only if** a follow-up stat of
`/proc/<pid>/ns/mnt` proves that namespace absent (`ENOENT` or `ESRCH`). If
that namespace exists, the stat fails for any other reason, or the mountinfo
file was opened before a parse/read/close error, refuse. An `EACCES`, `EPERM`,
`EIO`, or other unclassified inventory error always refuses. In particular,
`EINVAL` on mountinfo by itself is not a safe reason to skip a PID. Follow the
standalone formatter's corrected behavior, not its earlier permissive version.

On a successful inventory read, preserve the original root `dev_t` exactly and
keep these independent admission gates intact: active `/proc/swaps` entries
(including swapfiles whose filesystem backs the selected storage), Device Mapper
name/UUID and table ownership, selected/parent `holders` and `slaves`, and
source/parent topology. Unrelated host swapfiles need not be rejected solely
for existing. No mount scan substitutes for swap/DM/holder inspection.

## Final mutation boundary

The coordinator must repeat the cross-namespace mount admission **after all
intervening work that could race a mount** at the last safe boundary before
opening/writing a selected partition, changing a mapper, or activating swap.
It must recheck stable selected partition/parent and descriptor identity; retain
the same current-root identity, compare the target and parent against the newly
scanned tables, and refuse before *any* destructive side effect if the scan has
become busy or uncertain. A once-clean initial scan does not authorize a later
mutation. A rootless regression for this boundary requires exercising the
production lifecycle path with an injected late mount change and a write/ioctl
sentinel; source-order inspection alone does not qualify that behavior.

## Rootless regression expectations

The native test uses regular temporary files and mocked procfs path resolution,
never `mount`, `unshare`, a block device, or a physical card. It calls
`swapz_primary_read_mount_facts()` from production code and checks a sentinel
for attempts at destructive writes. Its baseline root is `259:0`; the other
PID's root is `259:9` and must never change that identity.

| Synthetic observation | Expected result |
| --- | --- |
| Local root only; unrelated PID or sibling `8:2` | Admit; preserve root `259:0` |
| Selected partition `8:1` only in PID `3031` | Refuse |
| Selected parent `8:0` only in PID `3031` | Refuse |
| Local or other PID mountinfo malformed or missing while namespace lives | Refuse |
| PID inventory or mountinfo permission denied | Refuse |
| Opened PID mountinfo has an I/O error | Refuse |
| `EINVAL`, `ENOENT`, `ESRCH` opening PID mountinfo, namespace still present | Refuse |
| Same errors, namespace proven absent | Admit if every other check is clean |
| Mountinfo missing while PID mount namespace remains | Refuse |
| Namespace stat itself permission denied or uncertain | Refuse |
| Active selected raw swap alias; matching DM ownership; nonempty holder directory | Independent refusal checks remain effective |
| Any refused admission | No destructive write |

The test is deliberately red against the verified `/proc/self/mountinfo`-only
implementation. Its failure is a useful P0 regression signal, **not** a
qualification PASS. Publication of a test does not close issue #94. The
remaining risks include hidden/inaccessible PID namespaces, detached mount
namespace FDs, stacked-filesystem aliases, cloned/reused device identities, and
time-of-check/time-of-use races; visible process scanning is not an atomic,
whole-host proof of physical device identity.
