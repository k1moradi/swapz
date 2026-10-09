# Independent main-developer audit — rootless fixture-owner broker

Review baseline: [`2f74389f1cc8fb8cfd45160e00e9230698253c17`](https://github.com/k1moradi/swapz/commit/2f74389f1cc8fb8cfd45160e00e9230698253c17), 2026-10-09.

## Scope and evidence

Reviewed the changed implementation and test bodies for:
`tests/runtime/recall-fixture-owner.py`,
`tests/runtime/recall-fixture-owner-test.py`,
`tests/runtime/recall-dd-allowlist.py` and
`docs/recall-fixture-owner-and-drain-evidence.md`.
The original source-only workflows both passed at this commit:
[combined](https://github.com/k1moradi/swapz/actions/runs/37959521965) and
[teardown](https://github.com/k1moradi/swapz/actions/runs/37959522042).
**Neither run invoked the new 15-test fixture-owner broker suite.**
Codex separately reported 15 locally passing cases and 382 total tests;
GitHub's generic PASS did not independently certify those 15 cases.

## Confirmed improvements

- `FixtureOwnerBroker.worker_request` admits only exact
  `{request_id, operation, role}` shape, `launch_role` and one of five
  fixed role strings, with replay check and assigned opaque worker handle.
  Arbitrary device paths, lifecycle commands, peer-supplied keys and raw
  observations are absent from the role request schema.
- The producer generates a fresh private 32-byte session HMAC key and
  internally submits ordered, canonical evidence to
  `FixtureBackingReleasePolicy`; the role API exposes only a final
  broker assessment, not a signed receipt.
- `MapperLifecycleOwner.release_mapping` returns typed inventory and
  release observations, requires positive `pending_io_drained` and
  strict normal-removal fields, and keeps `mapping_released` separate
  from the broker's backing-release policy result.
- No live device operations or backing unlink are exposed by this
  rootless module; the data source, peer identities and per-layer
  device observations are injected fakes.

## P0 — incomplete fixed recall role history can authorize backing release

The *successful* `test_end_to_end_owner_broker_and_producer_sequence`
calls `_start_workers()`, whose default is only
`('writer','a','b')`, then expects
`broker.backing_release_authorized == True`.
This is not a complete V2.2 recall execution
(`writer,a,b,a2,b2`). `worker_request` checks that a role
was admitted and registered; `finalize` checks only the
**observed** registered handle inventory, never the immutable
five-role inventory. `FixtureDrainEvidenceProducer._collect`
similarly derives the expected worker handles from what happened
to be registered rather than what the fixture required.

A truncated or even empty admitted-role inventory can therefore
pass the currently modelled completion checks if the injected
collector and operations agree with the truncated inventory.
**Do not use a positive broker backing authorization in any live
or privileged caller.** Codex owns this fix. Require an immutable
profile-bound exact set and phase ordering, per-role readback
attestation and complete handle inventory before any positive
assessment. Add negative tests for missing and reordered roles,
including the complete five-role profile.

## P0 — unknown worker created before a launch receipt is not owned

`FixtureOwnerBroker.worker_request` calls the injected
`_worker_launcher(role)` before a usable handle is assigned to
`_issued_handles`. On an exception after a child has been forked
but before the launcher returns a valid handle, `_best_effort_stop`
can stop only the **previously issued** handles. This is a
rootless model containment and owner-report gap. No live
worker is established to have escaped, but the architecture
cannot prove all children are owned/reaped on an ambiguous launch.
Require stable, supervisor-retained pidfd ownership before
acknowledgment, and adversarial tests for launch exception and
partial handshake. Any ambiguity must preserve backing.

## P1 — counter and process/credential boundary

`_request_inflight` is initialized to zero but not incremented
or decremented in the reviewed source. Its constant zero currently
adds no independent quiescence evidence. The broker's nonblocking
lock does serialize API calls and latches concurrent entry, but
the producer should not report a misleading independent
`request_inflight == 0` proof. Correctly count outstanding
operations or remove the redundant purported evidence field.

`_peer_authenticator` receives a fake identity-bound Python
object in tests; no `SO_PEERCRED` checking, private socket,
separate UID/capability isolation or independent root privilege
control is implemented. Public Python objects and private-by-name
attributes are not OS isolation. The model's owner and producer
must not be advertised as privileged or externally authenticated.

## P1 — single DM/loop graph only

The producer binds exactly one `DMIdentity` and a
`/dev/loopN` path. It cannot qualify complete upper/lower
dependency teardown or NBD disconnect. An authenticated model
receipt cannot prove ordinary kernel DM suspend/drain, open-count
zero, absent holders, normal DM removal, NBD disconnect or actual
backing preservation. A separate privileged trusted origin and
per-layer independent postchecks remain necessary.

## Parallel main-developer work

The main developer owns and patches
`.github/workflows/rootless-teardown.yml` and
`.github/workflows/rootless-combined.yml` to explicitly compile
and run the full broker suite with bounded timeouts. The teardown
push-path list now covers the new owner module and test. Separate
fresh-process repetitions should run fail-fast on any failure.
This catches regressions in model behavior; it does **not**
solve the P0 authorization gap and does **not** execute real device
operations.

See `VALIDATION.md` for exact later tested CI revision and
`TODO.md` for work ownership.

## Boundary retained

No real DM, loop, NBD, swap, kernel module, physical I/O,
destructive backing cleanup or production signer provisioning.
Production direct-mapper admission is disabled. The V2.2
strategy and batch size remain **UNDETERMINED**.
