# Rootless cross-process pinned recall qualification

**Scope:** Test-created regular files and direct workers only. This fixture
does not create a Device Mapper mapping, attach NBD/loop, enable swap or
authorize device teardown. The normal `test-child-supervisor-service.py`
CLI and normal `recall-control-bridge.py` CLI remain restricted to test
`sleep`/`exit` commands.

## What the new integration exercises

- `recall-role-process-integration-test.py` creates a private temporary
  directory, nine deterministic 4 KiB pages, and a separate exact-size,
  single-link **regular file** acting as the synthetic mapper.
- The test opens an AF_UNIX socketpair and synthetic mapper fd, then starts a
  *real separate* `Popen` service via
  `recall-role-process-fixture.py`. Only these two descriptors cross the
  subprocess boundary; the child's working directory is the private fixture.
- The helper rejects root execution and rejects any mapper descriptor that
  is not a private owned exact-size single-link regular file. It derives its
  fixture directory from the fixed subprocess working directory, not from an
  untrusted JSON request. The direct-`dd` executable is fixed to the local
  `/usr/bin/dd`, which is **not** independent GNU coreutils certification.
- Only this explicit fixture constructs `RecallDDLaunchGate` with
  `enable_direct_dd=True`; the ordinary service CLI cannot do so.
- The real `SupervisorControlService` and `GatedPidfdSupervisor` execute
  the five direct worker processes, exercising Codex's pinned executable FD,
  restricted role args, pidfd lifetime, process-creation filter and
  parent-death constraints. The actual `Popen` is bound to the client, and
  its observed exit code is compared before authorization.
- The gate wrapper captures the output's device/inode and holds the original
  file descriptor **before** releasing each worker. Only after a zero-exit
  pidfd wait/reap does the service read and verify the pinned output object
  against an independently generated deterministic reference page.
- A specialized, fixed `wait` receipt carries only the specific role,
  opaque worker handle, `verified=True` and SHA-256 of the pre-agreed page.
  The rootless-only client strips and validates the receipt *before*
  invoking the unchanged default strict `wait` response validator. It
  checks role/handle identity, digest, and replay denial. The role adapter's
  verifier checks the admitted role-to-handle mapping against that receipt.
  No caller-supplied `verified` field, path, descriptor, executable or
  mapper name is accepted.
- Successful stop requires exactly five verified role handles; the existing
  lower-level service must also return full stop/reap inventory, close gate
  descriptors without error, shut down and exit zero. The rootless bridge
  then closes its control descriptor. Only a **synthetic marker** can be
  removed following finalization.

The standalone tests cover a fully successful five-role process session,
replaced output pathname with valid bytes, immutable reference versus
source mutation, attempted writer wait before completed reads, service
SIGKILL through a pidfd, controller socket EOF, and premature A2 wait.
All negative paths must preserve the synthetic marker.

## Ownership and negative outcomes

The child service owns the pinned source, mapper-copy, executable and output
descriptors and every direct worker pidfd. The parent owns the service
`Popen` object, inherited socket client, temporary synthetic mapper's
creation and the final marker. All worker signals and reaping occur within
the gated supervisor. The crash test sends SIGKILL through a pidfd opened
specifically for the test-created service and **never** signals by raw PID.

A disconnect, invalid receipt, readback mutation, missing worker, failed
reap, service crash, close failure, malformed control response or ambiguous
observed service exit must deny finalization. Cleanup after test failure is
best-effort and cannot retroactively authorize backing teardown.

## What it does NOT prove

- The test-installed `/usr/bin/dd` is not necessarily GNU coreutils; the
  binary is not independently package/digest attested in this rootless path.
- A private same-UID process can still modify the contents of the pinned
  source or output inode in place. The immutable reference catches wrong
  bytes at verification time but cannot prevent later writes.
- A specialized response receipt comes from the trusted process over a
  private socket; it does not create a cryptographic trust boundary against
  a compromised service. Production would require an independent trusted
  bootstrap and audited service identity policy.
- No privileged Device Mapper table identity, exclusive lifecycle lock,
  kernel in-flight BIO drain, normal/forced teardown behavior, swap
  correctness, GC latency, lower-device bandwidth or performance has
  been tested.
- A worker's process death is **not** sufficient proof of kernel-side I/O
  quiescence or permission to remove backing after an abnormal failure.

For benchmark prerequisites and the separate authorization rules, see
`docs/v22-virtual-benchmark-qualification.md`.
