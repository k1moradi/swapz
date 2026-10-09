# Independent main-developer review — fixture ownership and writer-readiness containment

Date: 2026-10-09.

## Codex implementation reviewed

Commits:
- [`d168378c` — pinned GNU build-output binding](https://github.com/k1moradi/swapz/commit/d168378c28f755908b872e1c05583ccf5efc604d)
- [`837b0059` — mapper-only vs backing release](https://github.com/k1moradi/swapz/commit/837b0059d2bb416207ff95da5868b87b6943845f)
- [`c0e9b7d6` — contradictory drain receipts](https://github.com/k1moradi/swapz/commit/c0e9b7d6826b634b08bd45a525694bea236c2974)

The main developer inspected the implementation and concrete file diff:
`tests/runtime/recall-dd-allowlist.py`, its tests,
`tests/runtime/recall-fixture-release-policy.py`, its tests and
`docs/recall-fixture-owner-and-drain-evidence.md`.
No review conclusion substitutes for independent GNU static rebuilding,
production trust provisioning or real privileged/kernel qualification.

### R1 — previous GNU inspection and build-record deficiencies addressed in source

`gnu-coreutils-qualification.py::_inspect_binary` performs passive
descriptor-pinned ELF, metadata and SHA-256 checks. It does not launch
an untrusted candidate merely to parse its `--version`. The updated
`recall-gnu-dd-seccomp-qualification.py::_read_build_attestation`
validates a strict two-output record and independently hashes both
concrete outputs through pinned, private directory/file descriptors,
enforcing identities, duplicate avoidance and matching digests.
Its build comparison remains **same-host evidence**; an independent
builder and administrator-signed production manifest do not exist.

### R2 — mapper-only authority correctly separated from backing release

`MapperLifecycleOwner.mapping_released` requires normal removal and
confirmed absence under a cooperative lease. The owner no longer
exposes `cleanup_allowed`; its `backing_must_be_preserved` is
unconditionally true. Fixed role admissions and worker-handle
registration are reconciled, and typed completion evidence must be
authenticated by injected owner operations. Rejecting concurrent
model calls, a lost lease, an unexpected identity or a failed normal
removal preserves backing. These are testable rootless *policy*
properties, not enforceable exclusion of a host-root DM table actor.

### R3 — HMAC origin is not kernel evidence

`FixtureBackingReleasePolicy` requires ordered, canonical,
session-key-authenticated evidence for admission closure, workers,
swap inactivity, exact DM suspend/openers/normal removal/absence
and lower loop disappearance. It rejects stale, duplicate, malformed
and contradictory receipts; authenticated reports are a useful
interface boundary.

**HIGH remaining blocker:** A valid session HMAC proves only that
the holder of the current key signed the payload. It does not prove
the claimed `pending_io_drained`, complete holder inventory,
ordinary DM suspend, or normal loop/NBD disconnect actually
happened. There is not yet a separately privileged evidence
producer with exclusive lifecycle authority and independent
kernel postcondition verification. The current operations are
injected/fake. Do not expose backing deletion, device detach or
production mapper admission on the basis of a rootless model PASS.

### R4 — independent recall fixture failure diagnosed and contained

The [previous failed teardown run](https://github.com/k1moradi/swapz/actions/runs/37923337369)
returned `service_status=lifecycle_failure` and a pinned 4096-byte
readback mismatch during a positive reader WAIT. The short synthetic
writer was still populating its ordinary-file backing; the readback
oracle correctly denied the inconsistent page.

The main developer subsequently added a test-owned bounded
writer-data barrier. This turn hardened it to permanently deny
the controller, role adapter and client on uncertainty, close the
control connection, and prevent any later reader phase. Every
observation uses `O_NOFOLLOW` and a pinned private regular-file
descriptor; ownership, link count, mode, exact size, bytes and
path identity must remain consistent. Service exit, read failure,
timeout, symlink/path replacement and incorrect data are denials.
This does not establish worker reaping, nonvolatile persistence or
kernel I/O drain.

Ten additional adversarial integration tests cover delayed/partial
and incorrect bytes, stale/replaced identities, injected read
interruption, invalid deadline, unexpected service exit, and
failure after admission of an actual writer role. The full
20-case separate-process integration suite passed in both mandatory
workflows along with six independently fresh, strict positive
five-role process repetitions in **each** workflow.

### Exact-revision validation

Source SHA: `08f28d60648ce501ad6c86648db4f486f404994d`.

- [Combined workflow](https://github.com/k1moradi/swapz/actions/runs/37957362142): PASS; 20-case recall integration, six independent five-role
  positive repetitions, GNU policy 7+10, 81 allowlist,
  fixture-release model 5, 27 offline plateau, and 25/25 NBD repetitions.
- [Teardown workflow](https://github.com/k1moradi/swapz/actions/runs/37957362071): PASS; 20-case recall integration, six independent five-role
  positive repetitions, GNU policy 7+10, 81 allowlist,
  fixture-release model 5, and 27 offline plateau.

Both runs are rootless/source-only. The intermediate tests at
`d1e232a1` failed **only** because the inode-substitution denial
was emitted by the final-identity branch instead of the earlier
polling branch expected by the test. The failure was resolved by
accepting either identity-denial wording; the security predicate
was not relaxed.

### Outstanding qualification boundaries

1. Trusted privileged fixture owner and origin-authenticated
   kernel operation/result collector — NOT IMPLEMENTED.
2. Independently reproduced GNU binary and separately provisioned
   production Ed25519 signing key/manifest — NOT QUALIFIED.
3. Real DM suspend flush/I/O drain, complete holder/open-count
   checks, normal removal, exact loop/NBD disconnect — NOT RUN.
4. Virtual/physical benchmark and independently collected swap-in
   p99 — NOT RUN. Strategy and batch winner remain UNDETERMINED.
5. Rootless writer-content observation is a **fixture-specific
   ordering condition**, not a kernel fence or an irreversible
   writer-completion proof.

No DM, loop or NBD attach, swap operation, kernel module, device
benchmark, physical-media write or destructive cleanup occurred.
Both previously untracked `.state` files are outside GitHub
editing and were not opened or modified.
