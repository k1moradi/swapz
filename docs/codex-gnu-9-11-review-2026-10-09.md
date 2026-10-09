# Main-developer review: GNU 9.11 qualification and worker boundary

Reviewed code revision: `9070372f5d8da9d78f0ffefda89e46fb2c3e9126` (2026-10-09).
The diff adds GNU provenance/build verification and a real GNU worker
regular-file qualification harness; it touches only the GNU qualification,
allowlist test/implementation and documentation files listed in
[the commit](https://github.com/k1moradi/swapz/commit/9070372f5d8da9d78f0ffefda89e46fb2c3e9126).
No kernel source or live-device fixture changed.

Both reported **source-only** GitHub Actions completed on this exact SHA:
[combined](https://github.com/k1moradi/swapz/actions/runs/37919463175)
and [teardown](https://github.com/k1moradi/swapz/actions/runs/37919463332).

## Evidence we can and cannot independently confirm

The committed `docs/gnu-coreutils-9.11-qualification.json` reports
GNU 9.11 release SHA-256
`394024eda0a5955217ceda9cd1201e65dc8fa3aa29c2951135a49521d57c3cc3`,
pinned GNU signer fingerprint
`6C37DC12121A5006BC1DB804DF6FD971306037D9`,
and two byte-identical same-host static x86-64 `dd` outputs with SHA-256
`8b418fb762e099ca7f46ce34d5c8dafa006c757d317bd60f0194891ca4144180`.
The execution record reports five exact role outputs, a cancellation test,
and pidfd/seccomp containment on **ordinary files**.

The primary developer examined the verifier code and both checked-in
records, but has **not independently rerun** that GNU source download,
GPG verification, static build or real-GNU worker execution on a
separate host. GitHub's standard rootless workflows at Codex's
revision did not invoke the new GNU source/build test suites or
perform a real signed-source static build. Therefore those workflows'
green results must not be presented as independent verification of
Codex's source/build/run record. The records are local, generated
qualification evidence requiring separate reproduction and review.

## R1 — HIGH: inspecting a candidate executes it outside child containment

`gnu-coreutils-qualification.py::_inspect_binary()` opens a
descriptor, hashes and checks static ELF properties, then invokes
`/proc/self/fd/N --version` using ordinary `subprocess.run()`.
A locally supplied candidate has not acquired production trust
merely by matching a local self-reported record. The ELF headers and
version response are not proof that its code is harmless.

Running an untrusted candidate outside the tested pidfd/seccomp
worker boundary is an execution trust-boundary violation in a
qualification utility. Codex should remove unconfined execution:
perform passive validation first and move functional identification
into the already restricted worker fixture (or deny it). Add an
adversarial fake candidate that would create a marker if executed,
and demonstrate passive inspection cannot do so.

## R2 — HIGH: recorded repeatability is not independently rechecked

`recall-gnu-dd-seccomp-qualification.py::_read_build_attestation()`
accepts `build_count=2` and `same_host_byte_identical=true` from a
caller-supplied JSON file. It checks the *candidate's path* belongs
under one of the two expected build-tree locations and later checks
its digest, but does not independently hash the other output or
verify every digest in `sha256_by_build`. An altered record can
misrepresent local repeatability. The word `attestation` in this
local unsigned record must not be treated as trusted authority.

Codex should pin and independently hash both exact output files,
check their identities and their declared digests, and reject missing
or replaced artifacts. Even then, two builds on one host are not
independent builder reproduction. A separately signed,
administrator-reviewed build/provenance record remains necessary
before production provisioning.

## R3 — MEDIUM: fixed source signature is not independent binary trust

The helper checks an allowlisted archive checksum and a detached
GPG signature with the specified full release fingerprint; the
source record explicitly distinguishes GNU release authentication
from application binary trust. Its build tool versions and hashes
are recorded but do not authenticate the host compiler, linker,
libc or GPG dynamic runtime. Manifest signing in the worker
qualification uses a disposable test key plus mocked root metadata;
this proves mechanics, not production trust provisioning.

The trusted production public key and signed manifest remain absent,
independent reproducibility remains outstanding and the verifier's
dynamic OpenSSL loader/providers remain in the trusted host OS
closure. Keep direct mapper admission disabled.

## R4 — HIGH: kernel authority and I/O drain remain untested

A synthetic regular-file mapper verifier is intentionally used for
real GNU worker execution. Worker exit/pidfd reap does not prove
outstanding kernel block I/O has drained. Cooperative ownership
checks do not exclude unauthorized privileged table changes.
`MapperLifecycleOwner.cleanup_allowed` must not be interpreted as
full backing cleanup authority. A separate enforced privileged
owner and independently checked ordinary DM suspend, exact normal
removal, loop/NBD dependency clearance and kernel I/O quiescence
are still required.

## R5 — MEDIUM: new GNU unit tests were not mandatory CI steps

At the reviewed revision, neither source-only workflow explicitly
ran `gnu-coreutils-qualification-test.py` (seven synthetic policy
tests) or `recall-gnu-dd-seccomp-qualification-test.py` (four
build-record tests). The main developer subsequently added both
to the mandatory teardown and combined gates with bounded timeouts
and path triggers. Their synthetic coverage is **not a live
GNU source rebuild**.

## R6 — MEDIUM: separate-process short-worker startup evidence

Earlier source-only combined runs sometimes rejected 4 KiB recall
role launches as `unconfirmed or duplicated recall role worker`.
The supervisor intentionally distinguishes verified exec from
ambiguous early child exit. Because `wait_for_exec()` returns
`child-exit` if pidfd has exited when the exec-error pipe reaches
EOF, fast child completion can cause safe admission denial rather
than an authorization verdict. This timing hypothesis should be
tested; it is not proof that every observed earlier failure came
from the same cause. No readiness validation should be removed
or weakened to make the tests green.

A rootless-only diagnostic retains the bounded server launch status
and error. The separate process integration test accepts an early
fail-closed launch denial in the deliberately corrupted source case,
while keeping the positive five-role test strict. Repeated positive
admission tests run in independent fresh fixture processes to
surface unresolved timing failures and preserve test backing.

## Explicit scope

These findings were recorded while Codex owns GNU qualification,
allowlist and mapper-owner implementations. No main-developer code
changes were made to those Codex-owned files.

No actual DM/loop/NBD, swap operations, module loading, device
benchmark or physical data operation was performed. No strategy
or batch winner can be inferred. Both pre-existing untracked
state files must remain untouched.
