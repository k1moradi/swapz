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
evidence producer. At session creation it binds the immutable
`v22-recall-five-role` profile: exactly `writer`, `a`, `b`, `a2`, and `b2`, in
that order. A three-role or otherwise partial run cannot be finalized. Each
role has one unique opaque handle and one authenticated completion result with
exit status zero, confirmed reap, closed role descriptor, and no errors. The
session HMAC policy receives the same ordered handle and role inventories and
rejects missing, duplicate, reordered, contradictory, or unsuccessful rows.

The two final read roles use a two-phase launch. The broker requires both
`a2` and `b2` to return pidfd-owned READY receipts while held behind their
start gates, then calls the supervisor's group-release operation. The first
role's IPC reply says `ready_gated`; the pair does not begin until both are
registered. The fixed profile cannot be changed by worker IPC. A separately
named optional NBD profile uses the same five roles and adds independent NBD
release checks.

The injected launcher contract is `launch(role, startup_timeout)`, returning
only after the direct child is owned by a pidfd, has completed a bounded READY
handshake, and remains gated. The broker registers the opaque handle before
releasing work. The launcher must retain all children created before a usable
handle is returned and implement `stop_unconfirmed()`; cleanup calls this
even when no handle was registered. It then stops registered handles through
the supervisor. Both inventories are attempted independently, so a failure
stopping unconfirmed children does not skip attempts for registered handles;
either failure still latches denial and preserves backing. Launcher errors,
lost READY, duplicate handles, release errors, incomplete stop reports, or
unresolved request accounting latch denial. A delayed READY is never
acknowledged. The injected launcher is a
trusted component boundary: Python cannot safely preempt a malicious or
permanently blocked in-process callback. A production launcher must enforce
its own monotonic startup deadline and retain its private child inventory.
Every READY receipt also names the required no-fork containment profile. After
direct-child completion, the producer requires a separate complete
session-bound launcher inventory for all five worker process domains. A
missing inventory, direct-child-only scope, duplicate or unknown domain,
reported descendant, stale session, or inspection error denies the session
before swap inspection or mapper release begins.

The broker's `serve_worker_connection()` accepts one bounded AF_UNIX stream.
It reads PID, UID, and GID from kernel `SO_PEERCRED`, compares all three with
the identity captured by trusted bootstrap, pins one connection for the
session, and rejects replacement connections. Frames have a fixed maximum
size, an absolute read deadline, unique JSON keys, exact request fields, and
one-use request IDs. The role-only request contains no credentials, mapper,
PID, executable, argv, output path, operation result, key, or receipt. The
direct `worker_request(peer, ...)` method remains only an injected unit-test
seam; live adapters must use the socket method. Rootless tests include a
separate client process so the kernel-reported peer PID differs from the
broker PID. The socket test is not a security boundary against host root or
another process running under the same fixture-owner credentials.

The producer creates its own session HMAC key, keeps the key and
release-policy instance private, and exposes no event-signing or submission
method to worker requests. Create, suspend, remove, swapoff, loop detach and
evidence collection are owner-side methods; they are absent from the worker
request schema. Worker evidence includes the full fixed role results, not
just the handles observed after the fact. It derives swap state from
before/after inventory, DM release evidence from the typed report returned by
`MapperLifecycleOwner`, and lower/loop evidence from fresh typed inventory
results. The owner still requires ordinary flushing suspend, a positive
pending-I/O-drained observation, complete zero-opener/empty-holder evidence,
typed normal removal, and exact post-removal absence.

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

The broker lifecycle is one-way, with a synchronized abort boundary:

```text
NEW --trusted owner create--> ACTIVE
ACTIVE --fixed worker-role IPC--> ACTIVE
ACTIVE --trusted owner finalize--> FINALIZING
FINALIZING --complete evidence sequence--> RELEASED
any pre-commit state --credential ambiguity / EOF / operation error / concurrency--> DENIED
```

`FixtureOwnerBroker` uses a short-held state lock and an active-operation
reservation. The reservation serializes owner creation, each role request,
EOF handling, and finalization without holding a mutex across injected calls
that may block. The state lock protects the reservation, denial latch,
admission flag, request-inflight count, and final release commit. A competing
lifecycle call sees the reservation, takes the state lock, and latches
`DENIED`; it does not mutate worker ownership or stop workers while the active
operation owns the worker inventory. The active operation checks the latch
before its next modeled operation. On unwinding, it clears the reservation
before best-effort `stop_unconfirmed()` and `stop_all()` are attempted. Both
stop paths are attempted independently, and any failure leaves denial sticky.

The state-lock acquisition is the linearization point for both denial and
successful final release. A finalizer may commit `RELEASED` only while holding
that lock and only if no denial has already latched. If denial wins, the
finalizer cannot return success and the next operation checkpoint raises
before another modeled operation begins. If the commit wins first, the session
is terminal; later calls are rejected without rewriting the already committed
result. Operations already past their checkpoint may finish, so this model
does not preempt a blocked operation. It checks again before every following
operation. No lock is held while waiting for injected worker/evidence calls or
while stopping workers.

`MapperLifecycleOwner.release_mapping()` accepts the broker's private
checkpoint callback and checks it before authentication/inventory, ordinary
suspend, retained-descriptor close, holder inspection, normal removal, absence
verification, and lease release. The producer likewise checks before swap,
DM, NBD, lower-dependency, and loop operations. This defines rootless control
flow and does not make the callback atomic with kernel state or an unrelated
privileged actor.

`RELEASED` means that the synthetic sequence's backing-release policy
accepted. It does not delete a backing file, invoke a production teardown
command, or prove actual kernel quiescence. `MapperLifecycleOwner.mapping_released`
remains a separate mapper-only result. The broker requires both values plus a
clean terminal state before exposing `backing_release_authorized`.

## Worker process-tree containment contract

A successful direct-child pidfd wait is never evidence that every process
created by that worker has stopped. The required production contract is:

1. The trusted launcher owns each worker from creation through confirmed
   termination and separately identifies its containment domain.
2. The domain covers descendants. Workers cannot fork, vfork, or create a new
   process through clone/clone3 outside it.
3. Process-group or session IDs are never used as domain identity. A group
   change cannot detach the same thread group from its retained pidfd. The
   profile denies credential and namespace transitions that could clear the
   parent-death binding or change isolation. Executable identity and fixed
   argv are validated separately; this process filter does not itself pin an
   executable image or prohibit `execve`.
4. The containment mechanism remains effective if the fixture owner or worker
   supervisor exits. A direct-child pdeath signal alone is not a process-tree
   guarantee.
5. The owner receives a complete, session-bound inventory for every expected
   handle/domain. Missing, ambiguous, stale, contradictory, or unauthenticated
   inventory permanently denies release.
6. Numeric PIDs, reused PIDs, process-group membership, HMACs, READY receipts,
   and direct-child wait status do not count as independent tree-quiescence
   evidence.
7. Rootless mechanism tests, privileged containment authority, and kernel
   I/O-drain behavior are separate qualification claims.

The rootless `GatedPidfdSupervisor` profile sets `PR_SET_PDEATHSIG` and installs
`no_new_privs` plus seccomp before exec and before releasing the worker gate.
The filter rejects new process creation while permitting same-thread-group
threads; a separate post-READY test confirms that a worker's fork attempt gets
`EPERM`. The filter therefore prevents a worker descendant from being created
after the trusted pre-exec setup. Its direct-child `StopReport` now exposes a
separate `process_tree_quiescent` result and denies its cleanup callback when
the worker was only directly supervised. The five-role broker independently
requires the complete containment inventory; it does not infer that inventory
from the worker-completion HMAC.

The protocol-v2 broker path also has a rootless end-to-end test that executes
the fixed five regular-file `dd` roles through an actual supervisor service
process and its `SupervisorControlClient` adapter. The supervisor's private
`Worker` record supplies the supervisor ID, opaque handle, lifecycle ID,
`pidfd_owned_at_launch`, and containment profile recorded only after the
pre-exec setup and exec handshake succeeded. The service cross-checks launch,
wait, and stop results against that same retained record, then exports the
session, service instance, supervisor, handle, role, lifecycle, direct-child
reaped status, exit result, and containment fields. The client requires every
stop row to match its READY receipt and complete launch history.
`SupervisorServiceWorkerLauncher` exposes the receipt set and finalized stop
snapshot; the evidence producer reconciles both against the fixed five roles
before it emits its session HMAC or starts any modeled swap/DM/lower-device
operation. Swap, mapper, lower-device, and loop operations remain fakes; the
test uses ordinary temporary files. Its `/usr/bin/dd` is pinned by the test
gate but is not checked against the GNU qualification manifest, so this
broker-chain test does not itself establish GNU provenance or GNU-specific
worker compatibility. That requires the separate authenticated GNU worker
qualification and its independently retained build inputs.

That chain is a trusted-process assertion, not a cryptographic or
kernel-authenticated attestation. The inherited private Unix socket and bound
service process identify which local service the client is talking to; they
do not protect against a compromised service, a process that obtains the
socket descriptor, or host root. The rootless `domain_id` is the supervisor's
opaque lifecycle ID, not a kernel cgroup ID. The service derives
`parent_death_bound` and `process_creation_denied` from the exact versioned
containment profile after its supervisor record reports successful pre-exec
setup; it does not independently inspect seccomp state from the kernel.
Direct-child reap remains a separate field. Neither that reap nor this
protocol proves that submitted block I/O has drained.

The no-fork profile does not use process-group scans or accept a process-group
change as evidence of containment. The fixed executable and argv policy must
separately prevent an untrusted image from replacing the intended worker. The
rootless five-role marker worker is a fixed Python test program; it is not
evidence that GNU `dd` is trusted or that arbitrary executable changes are
safe under the filter.

The adversarial rootless process test creates an intentionally uncontained
worker that forks a test-owned descendant and exits. It observes the direct
worker reaped while the descendant remains alive, then verifies the cleanup
callback is withheld. The test terminates only that descendant through a
pidfd retained while it was known alive and reaps it as a test subreaper. A
separate crash test kills the actual test supervisor and verifies its
pre-exec-contained direct worker exits. Together these are counterexample and
profile tests; they are not evidence about a privileged fixture or real device
cleanup. The real five-role test runs bounded regular-file marker workers
under the rootless no-fork profile and verifies a complete empty-descendant
inventory. It does not run GNU `dd` or device I/O.

`PR_SET_PDEATHSIG` applies to the immediate parent relationship and is not
inherited by descendants. The seccomp filter closes worker-created process
escape in the tested profile, but it does not establish a crash-survival chain
when a separately deployed broker, supervisor service, or privileged owner
dies. In production, either the trusted owner must directly supervise the
workers with the same pre-exec no-fork boundary and parent-death binding, or a
separately controlled crash-survival supervisor/cgroup manager must own and
terminate the complete domain. A cgroup is useful only if its owner and
failure policy survive the broker; merely placing workers in a cgroup is not
automatic kill-on-owner-death. The current rootless tests do not prove such a
production chain, cgroup authority, seccomp policy on every deployed kernel,
or absence of privileged actors that can escape the domain.

The AF_UNIX regression uses an actual listener and a separate rootless client
process. Kernel `SO_PEERCRED` supplies the PID/UID/GID; the broker rejects
credential mismatches, duplicate request IDs, malformed/oversized/partial
frames, early EOF, and replacement connections. This does not protect against
host root or another process sharing the fixture owner's UID/GID. A future
privileged deployment needs a distinct owner identity, private socket path,
strict peer credentials, close-on-exec descriptors, and capabilities limited
to the disposable fixture lifecycle. Workers must have no DM-control
descriptor, `CAP_SYS_ADMIN`, swap-control privilege, or access to the evidence
key. A host-root actor with sufficient kernel authority can still replace a
table; namespaces and a cooperative lock do not prevent that.

`LayeredDMReleaseModel` accepts an immutable upper-to-lower tuple of one to
eight unique DM identities. Every layer must independently report matching identity,
ordinary flush suspend (never `noflush`), drained pending I/O, closed
descriptors, zero openers, no holders, normal removal without force/deferred
mode, and exact name/UUID/device-number disappearance. Any failed layer
permanently denies the sequence. Its result is named
`mapper_dependencies_released`; `backing_must_be_preserved` remains true.
This rootless model is not wired into the current single-mapping owner report
and does not authorize actual backing cleanup.

The separate `v22-recall-five-role-nbd` profile binds a session-specific NBD
device and pidfd-owned server handle. It requires normal disconnect, a
confirmed server reap with its pidfd identity retained through disconnect,
server descriptor closure, and a fresh exact device/major/minor inventory
proving absence. NBD evidence is a separate producer precondition before
lower-dependency and loop checks. Loop detach never establishes NBD absence;
NBD disconnect never establishes loop absence. The model does not attach NBD
or prove actual kernel disconnect behavior.

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
