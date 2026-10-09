# Independent main-developer review: five-role fixture broker

Reviewed baseline: `2eab914665e58ac325c664212d1fed83793dba04`
Reviewed files: `tests/runtime/recall-fixture-owner.py`, `tests/runtime/recall-fixture-owner-test.py`,
`tests/runtime/recall-dd-allowlist.py`, and the release-policy implementation.
Scope: rootless model and authenticated synthetic evidence only. No privileged operations,
real backing deletion, independent producer attestation, or physical kernel drain qualified.

## Previously reported P0 issues: source-level disposition

- **Incomplete required roles:** the broker checks the immutable five-role sequence
  before finalization (`FixtureOwnerBroker.finalize`, lines 1051-1062).
  The producer independently checks the admission snapshot, registered handles,
  admitted roles, and ordered five-role results (lines 461-480, 679-705).
  Rootless negative prefix tests now run independently of Codex's suite. **Closed at
  rootless source-policy level, not production-qualified.**
- **Ambiguous launched child:** launch ambiguity is latched before `launch`;
  typed gated READY receipts are validated before registration (lines 997-1025).
  On denial, `stop_unconfirmed` and `stop_all` are attempted even
  when READY registration failed (lines 1203-1238). Independent negative tests
  exercise exceptions after synthetic child creation. **Rootless model closure
  supported; actual crash-resistant process-tree containment remains unproved.**
- **Paired reader admission:** `a2` is acknowledged as `ready_gated` until
  `b2` is admitted and the pair is released (lines 1028-1040).
  This models a joint launch gate, not verified simultaneous CPU execution.

## Concurrency issue requiring Codex follow-up

**Priority: P1 for source model consistency; escalate before a privileged owner exists.**

In `FixtureOwnerBroker._Guard.__enter__` (lines 1180-1184), a competing
lifecycle request may call `_latch` and `_best_effort_stop` *without*
holding `_lock`. If the trusted thread already passed finalization's
preflight checks and is blocked in `_producer.collect()` (lines 1051-1070),
the competing thread sets state to DENIED, but the finalizer does not recheck
`_denial` after collecting; it can set state RELEASED and return True.

`backing_release_authorized` independently requires `_denial is None`
(lines 878-885), so the observed permission interface still denies backing
release. However, contradictory successful return/state and continued synthetic
DM/loop teardown after a concurrent denial violate a stronger fail-stop
lifecycle invariant. An independent deterministic contention test now guards
the negative backing-permission boundary but does not claim this race fixed.

**Requested Codex remediation:** serialize contention denial with the lifecycle
operation or adopt a monotonic abort generation checked before every
irreversible operation and before successful finalization. Avoid initiating
child stops concurrently with evidence collection under an unheld lock.
Add a deterministic test demanding no successful finalization after denial
and no later removal/detach if the denial precedes those operations. Do not
weaken the five-role, credential, pidfd, or HMAC gates to make that test pass.

## Other remaining limits

- The socket reads real `SO_PEERCRED` (lines 920-950), but static peer
  credentials do not exclude same-identity actors or host root.
- `LayeredDMReleaseModel` is a separate policy model; the producer's
  real integration path still constructs an evidence policy for one bound mapper
  and a synthetic lower-dependency observation. Real multi-layer topology and
  NBD I/O drain are not independently observed.
- The production trust root, independent GNU binary reproduction, authoritative
  drain observations, and exclusive privileged owner remain unavailable.
- V2.2 strategy and batch winner: **UNDETERMINED**.

The added tests do not perform real mapper/swap/loop/NBD operations and cannot
authorize backing cleanup or any live experiment.
