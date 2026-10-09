# Main-developer review — Codex trusted GNU bootstrap and mapper owner

Reviewed: 2026-10-09. Code commit:
`d2240b06e8a8fc5649d407d0c0344308896196e0`.
Diff relative to `5c1948bf0c37f80972c9d4329dfc6308502dee8a` changes
**only** `tests/runtime/recall-dd-allowlist.py`,
`tests/runtime/recall-dd-allowlist-test.py`, and
`docs/recall-dd-allowlist.md`. The kernel source was not changed.
Review consulted the exact current code after Codex's commit and
reported same-revision rootless CI:
[combined](https://github.com/k1moradi/swapz/actions/runs/37912930826),
[teardown](https://github.com/k1moradi/swapz/actions/runs/37912930921).

## Findings (review outcome: source-only mechanisms improved, no live admission)

### R1 — HIGH integration hazard: mapper release is not backing cleanup authority

`MapperLifecycleOwner.cleanup_allowed` becomes `True` after its
single-mapper `finalize_teardown()` finishes normal removal, observes
the mapper identity absent, closes the cooperative lease, and enters
`RELEASED`. However, `finalize_teardown()` does **not** perform
ordinary kernel DM suspend/drain, inventory all DM layers, inspect loop
or NBD holder dependencies, or prove kernel I/O quiescence. It also
accepts `workers_reaped=True` and `descriptors_closed=True` from its
caller, without authenticating their source.

This is not an immediate production exploit because live mapper
admission is still disabled and no production fixture calls the owner.
It is a potential **fail-open integration mistake** if an eventual
caller interprets the property's name as permission to delete backing
files. Treat this positive state solely as **one mapper lifecycle
released**. Real backing release must additionally pass independent
`DMIODrainPolicy` evidence and backend-specific kernel NBD/loop
drain/absence checks. Do not let an arbitrary IPC boolean stand in for
verified worker/service receipts.

Recommended owner follow-up: rename or scope the positive property
to mapping-only success before production integration, or add a
separately audited composite teardown gate. Do not wire its current
`cleanup_allowed` directly to `rm`, `unlink`, loop detach, or
device power-off.

### R2 — HIGH qualification blocker: signed manifest != authenticated GNU provenance

`from_trusted_bootstrap()` now takes no external verifier/key/manifest
arguments and reads normalized fixed, root-owned paths through
descriptor-relative, `O_NOFOLLOW` traversal. It validates a strict
manifest, checks 64-byte detached Ed25519 signature with a pinned
OpenSSL path, and preserves the pre-existing descriptor hashing,
static ELF policy and sealed executable snapshot. Rootless regression
tests exercise disposable keys and synthetic ELF.

No real trusted static GNU coreutils `dd` build, independent GNU
source signature verification, reproducible build record, production
application-signing key or trust-anchor installation is provided.
The host `dd` is uutils. Therefore the positive regression proves
the verifier's mechanics, **not** the provenance of any real binary.
Production mapper admission must remain disabled.

### R3 — MEDIUM deployment closure: pinned OpenSSL executable does not pin loader/providers

The OpenSSL verifier executable's path, inode and metadata are checked,
but its dynamic loader, shared libraries and provider modules are not
individually captured in the trust manifest. Codex explicitly documents
reliance on the trusted host OS package closure. Before deployment,
independently review that OS closure, OpenSSL provider behavior,
key provisioning/rotation and the static GNU child seccomp/syscall
compatibility. Fail closed where the trusted closure cannot be
established.

### R4 — HIGH authority limitation: cooperative mapper lock is not exclusive kernel control

`MapperLifecycleOwner` binds one grammar-checked mapper identity and
tests owner liveness, lease, descriptor and full inventory repeatedly.
This is stronger than checking a name once. But injected owner
operations and cooperative `flock` cannot prohibit an uncooperative
privileged actor from issuing a DM ioctl between checks. A separately
controlled, auditable privileged fixture owner must establish enforced
exclusive table authority and handle controller death before real
mapper admission.

## Tests and remaining work

Codex reported 77 allowlist tests and passing same-revision rootless
workflows. These substantiate *policy/test coverage*, not live GNU
execution, kernel-enforced DM exclusive ownership or block I/O drain.
The owner and verifier files remain under Codex ownership for its next
authentic GNU/seccomp qualification task; this review intentionally
does not edit those files or weaken admission.

The primary developer owns subsequent **independent** NBD
parent-crash/descendant containment work and required rootless CI.
No source-only success permits real DM/loop/NBD attach, swap operations,
device benchmarks, or destructive cleanup without explicit separate
approval. Actual V2.2 strategy and batch remain **UNDETERMINED**.
