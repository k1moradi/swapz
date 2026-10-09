# Recall fixture owner and backing-release evidence

**Status: rootless policy qualification only.** A rootless broker model exists,
but no privileged broker, real DM mapping, swap transition, loop detach, or
backing-file cleanup is implemented or qualified. Production direct-mapper
admission remains disabled.

## Separate mapper release from backing release

`MapperLifecycleOwner` controls one injected mapping identity. Its
`mapping_released` property means the exact mapping was normally removed, its
name/UUID/device number were independently observed absent, and the
cooperative lifecycle lease was released. The owner has no `cleanup_allowed`
attribute and always reports `backing_must_be_preserved=True`. A caller must
not infer that a backing image can be deleted from mapper disappearance.

Before mapper-only release, the controller requires a typed
`WorkerCompletionEvidence` bound to the lease's random session ID. Its handle
inventory must match the handles registered with the owner exactly. Reaped and
role-descriptor-closed inventories must each match that same set; worker and
service errors must be empty; service exit must be zero; and the injected
trusted-owner verifier must authenticate the report. A pair of booleans is not
accepted. Every admitted role is bound to exactly one opaque worker handle in
admission order before admission can close; an unregistered admitted role or
unbound handle latches denial. The verifier is a trust boundary: the rootless
fake verifier only tests report reconciliation and HMAC handling.

The injected mapper owner uses this order:

```text
acquire exact fixture lease before creation
  -> prove owner alive and inventory valid
  -> create the one expected mapping and retain its descriptor
  -> verify the descriptor and name / UUID / major:minor / table fingerprint
  -> revalidate before each fixed-role admission
  -> permanently close role admission
  -> authenticate complete worker, service-exit and descriptor-closure report
  -> ordinary DM suspend with flushing semantics
  -> close the retained mapper descriptor
  -> re-inventory exact mapper identity after suspend and descriptor close
  -> independently verify complete open-count and holder inventory is empty
  -> re-inventory exact mapper identity immediately before removal
  -> normal removal, without force or deferred removal
  -> independently verify exact name, UUID and device number are absent
  -> release the cooperative lease
  -> mapper_released only; preserve backing
```

The owner exposes no table reload operation. Its fixed operations interface
allows create, identity inventory, ordinary suspend, open-count/holder
inspection, and normal removal for the single bound identity. Identity or
inventory changes latch denial. The model does not run these operations.

## Privileged owner boundary still required

A future live fixture needs a dedicated, separately reviewed privileged owner
or broker. It must acquire lifecycle authority before mapping creation and be
the only process allowed by the fixture's credential boundary to create,
reload, rename, suspend, or remove that disposable table. Worker IPC must not
accept mapper commands and must not hold a DM control descriptor or
`CAP_SYS_ADMIN`. The broker must retain root-controlled executable and
configuration ownership, use private authenticated IPC, close-on-exec
descriptors, and bind one exact name, UUID, major/minor and table identity.
Any crash, lease loss, ambiguous inventory, unexpected privilege, or failed
identity check preserves the backing.

Namespaces and `flock` do not prevent host root from issuing privileged DM
operations. A host-root actor with the necessary kernel authority cannot be
excluded by this cooperative model. The rootless fake owner demonstrates
ordering and failure behavior, not kernel-enforced exclusivity.

## Session-bound kernel drain evidence

`tests/runtime/recall-fixture-release-policy.py` defines a typed evidence
envelope containing `session_id`, monotonically increasing `sequence`, exact
`event`, canonical JSON payload bytes, and a 32-byte HMAC. The MAC covers the
session, sequence, event and payload. The validator rejects replay, stale or
foreign sessions, duplicate JSON fields, noncanonical payloads, unknown or
out-of-order events, and every missing, contradictory or malformed value. A
denial is sticky. Its only positive property is named
`backing_release_authorized`; the mapper owner cannot set it.

The fixture-owner event sequence must report:

1. Admission closed and no more role launches possible.
2. Complete worker inventory; every expected handle reaped; role descriptors
   closed; no worker errors; service exit verified as zero.
3. Independently inspected swap state. If the exact test mapper is active as
   swap, successful `swapoff` and an independent post-check must prove it is
   inactive.
4. For each DM layer, upper to lower: successful ordinary suspend, ordinary
   flush semantics, no `--noflush`, no timeout, matching bound identity, and a
   positive kernel-side pending-I/O-drained result.
5. All owner and worker descriptors closed, with no close errors.
6. Complete DM open-count inventory at zero and an empty holder list for the
   same identity.
7. Successful normal removal only. Force and deferred removal are forbidden.
8. A fresh complete inventory proving the exact name, UUID and device number
   absent. For the fixture-owned mapper, this includes the authenticated
   mapper-only release receipt for this session.
9. All upper/lower DM dependencies absent and the exact loop holder inventory
   valid and empty.
10. Successful normal detach of the exact loop and a fresh inventory proving
    that exact loop absent. NBD-backed fixtures would additionally require
    their exact normal disconnect and independent absence evidence.

Unknown, stale, contradictory, incomplete, unauthenticated, failed, timed-out,
or unobservable evidence always means preserve backing. A pidfd worker reap is
not a kernel I/O barrier. Ordinary DM suspend is the planned kernel boundary
for I/O already submitted through the mapped target; it is not a claim that
data reached nonvolatile media. A timed-out suspend, unclear open count,
failed normal removal, or missing holder inventory is a preservation case.

The session HMAC is an integrity/authentication interface, not a magic source
of kernel truth. The key must be created or provisioned by the trusted fixture
owner, remain outside worker IPC, and be bound to the current fixture session.
The collector must produce evidence only after it directly verifies each
underlying operation and its post-state. The test key used by the rootless
regression is disposable and does not authenticate any actual system state.

## Rootless broker and evidence producer

`tests/runtime/recall-fixture-owner.py` adds a test-only owner broker and
evidence producer. The producer creates its own session key, keeps the key and
the release-policy instance private, and exposes no event-signing or
submission method to worker requests. Workers may request only a fixed role
launch with an opaque request ID. They cannot supply executable arguments,
mapper identity, operation outcomes, keys or evidence receipts. The broker
supplies worker handles from its injected supervisor launcher and registers
each handle with `MapperLifecycleOwner`. Create, suspend, remove, swapoff,
loop detach and evidence collection are owner-side methods; they are absent
from the worker request schema.

The producer calls injected operations and accepts only exact observation
types. It derives worker evidence from the supervisor report, swap state from
before/after inventory, DM release evidence from the typed report returned by
`MapperLifecycleOwner`, and lower/loop evidence from fresh typed inventory
results. `MapperLifecycleOwner` now requires an explicit pending-I/O-drained
observation and a typed normal-removal result (`force=false`,
`deferred=false`) before returning that report. The report binds the lease
session and exact name, UUID, major/minor and table fingerprint, with fresh
inventory snapshots after suspend/descriptor closure, before removal, and
after removal. The producer submits canonical HMAC envelopes only to its
private in-process validator; it returns a final assessment, not a reusable
receipt or the key.

The HMAC is not the source of truth. It protects the internal report format
and session sequencing after the producer has inspected operation results. A
rootless producer can still only prove what its injected fake says happened.
The tests do not exercise kernel DM, swap, loop, holder, open-count or pending
I/O observations, and they do not establish that the HMAC key is inaccessible
to another process. Python object privacy is not a security boundary against
same-process code. The production design must run the collector in a
separately controlled owner process, derive peer credentials from the IPC
transport, and keep the key inaccessible to workers and untrusted controller
IPC.

The broker state is one-way:

```text
NEW --trusted owner create--> ACTIVE
ACTIVE --fixed worker-role IPC--> ACTIVE
ACTIVE --trusted owner finalize--> FINALIZING
FINALIZING --complete evidence sequence--> RELEASED
any state --credential ambiguity / EOF / operation error / concurrency--> DENIED
```

`RELEASED` means that the synthetic sequence's backing-release policy
accepted. It does not delete a backing file, invoke a production teardown
command, or prove actual kernel quiescence. `MapperLifecycleOwner.mapping_released`
remains a separate mapper-only result. The broker requires both values plus a
clean terminal state before exposing `backing_release_authorized`.

The rootless tests model the trusted peer authenticator with identity-bound
Python objects. A real broker would need a private Unix socket, strict
`SO_PEERCRED`/credential validation, a dedicated service identity, a
root-controlled configuration directory, close-on-exec descriptors, and
capabilities limited to the disposable fixture lifecycle. Worker processes
must have no DM-control descriptor, `CAP_SYS_ADMIN`, swap-control privilege,
or access to the evidence key. The worker protocol must remain role-only and
must never accept arbitrary device paths or lifecycle commands. A host-root
actor with sufficient kernel authority can still replace a table; namespaces
and a cooperative lock do not prevent that.

This prototype processes one DM mapping and its exact loop dependency. It
does not implement a privileged multi-layer DM collector or NBD disconnect
collector. A future layered implementation must repeat the exact ordered
suspend, descriptor, open-count/holder, normal remove and absence observations
for every bound layer before checking lower dependencies.

## Operating-system and kernel qualification

The real owner must be tested on the target kernel and DM target stack. It must
verify that ordinary `DM_SUSPEND` returns only after the expected mapped I/O
drain, account for all openers and holders, and retain the backing if any step
fails. It must use bounded retries where retry is safe but never infer
quiescence from an expired timeout. It must not use force, deferred removal,
or noflush as a shortcut. Only after exact upper-to-lower teardown and
independent loop/NBD absence checks may a separate backing-release operation
be considered.

The rootless model uses synthetic identities, private regular files and fake
operations. It does not execute `dmsetup`, open `/dev/mapper`, activate or
deactivate swap, detach loops, or authorize actual file deletion. A future
privileged integration needs separate review and runtime authorization.
