# V2.2 rootless fixed-role recall bridge and pinned readback

**Status:** Test-owned source qualification. The normal bridge CLI and normal
pidfd service CLI remain restricted to fixed `sleep`/`exit` workers. Production
`buffer-recall.sh` is unchanged; live mapper operation and teardown are disabled.

## Division of safety responsibilities

- `recall-dd-allowlist.py` is Codex's opt-in trusted direct-`dd` launch
  gate. The service's production CLI never constructs or activates that gate.
- `recall-readback-identity.py` is an independent readback attestor. A
  trusted caller must capture identity **after exclusive output creation and
  before starting the worker**, then retain the directory and O_WRONLY output
  descriptors until the worker is reaped and verification succeeds.
- `RecallRoleIPCAdapter` is a separate, explicitly constructed adapter for
  the five fixed roles: `writer`, `a`, `b`, `a2`, `b2`. It never accepts
  arbitrary argv, paths, PIDs or executable names. It records every opaque
  handle, forbids duplicated/reordered roles, and requires all five workers
  to be successfully waited/reaped before `STOP_ALL` can authorize even a
  *synthetic* cleanup.
- `RootlessRoleBridge` is the test-only Bash-facing adapter. Its constructor
  requires the exact opt-in adapter/client/process objects already owned by
  the test harness. It is not called by `recall-control-bridge.py`'s
  `main()`; ordinary Bash callers cannot turn on role mode via JSON,
  command-line flags or environment variables.

The test-only `LAUNCH_ROLE` message has exactly `id`, `op` and `role`.
The remaining `WAIT`, `STOP_ALL`, `SHUTDOWN` and `FINALIZE` states retain
the default bridge's strict monotonic-ID and cleanup protocol. No role worker
PID is returned to Bash.

## Exact readback identity

A pinned output descriptor opened `O_WRONLY` cannot be read using `dup()`:
the duplicate inherits the write-only open-file description. The verifier
therefore reopens the **retained descriptor** via
`/proc/self/fd/<output_fd>` with `O_RDONLY|O_CLOEXEC|O_NONBLOCK`, rather
than trusting a potentially replaced `read-<role>` pathname.

It rejects:

1. Non-private or unowned directory objects.
2. Wrong, multiply linked, unowned or writable-by-others output objects.
3. Changed `(st_dev, st_ino)` for the retained directory or output.
4. Missing, replaced, hardlinked or symlinked output directory entries.
5. Readback length other than exactly 4096 bytes.
6. Any byte difference from an independent immutable expected page.
7. Descriptor open, read, metadata verification or close failures.

It rechecks the entry and pinned descriptor after the bounded read. Borrowed
descriptors remain owned by the trusted fixture, not by the verifier.

A same-UID adversary that can mutate the *same inode's contents in place*
remains a separate threat, as does replacement after the final validation
instant. Trust requires a truly private fixture and an external immutable
reference. This verifier does not lock files, attest the DM table or prove
atomicity against a privileged attacker.

## Rootless qualification

The added regressions have distinct scopes:

| Test | Boundary |
| --- | --- |
| `recall-readback-identity-test.py` | Descriptor and pathname spoofing, size and data poisoning |
| `recall-role-bridge-test.py` | Five-role adapter, sticky denial and synthetic cleanup gate using a fake IPC client |
| `recall-role-service-integration-test.py` | Actual AF_UNIX service/client wire protocol and Codex role gate with an injected non-forking fake supervisor |
| `recall-role-bridge-fixture.py` and `recall-role-bridge-regression.sh` | Genuine Bash coprocess protocol against temporary regular-file synthetic worker responses |
| `recall-dd-worker-integration-test.py` | Real pinned GNU `dd` process against temporary regular-file synthetic mapping |

The in-process service regression does **not** prove the exact service
*process's* exit; its process shim only waits for the exact service thread.
The standalone Bash fixture also uses a fake service, and can authorize only
a synthetic marker. Both are intentionally separated from the real pinned
worker regression.

A production service process currently does not send a trusted output
descriptor or prelaunch `(st_dev, st_ino)` attestation through its IPC
protocol. Therefore the bridge cannot independently prove that a readback
path was the object written by the separately executing service process.
Passing a pathname and checking it after completion would reintroduce the
TOCTOU failure. A reviewed trusted bootstrap needs to retain and bind those
identities across the service boundary (or perform comparison inside the
trusted gate before releasing final cleanup authority). No generic fd/path
wire operation should be introduced to solve this.

The rootless tests **do not** prove cgroup descendant containment, survival
after supervisor crash, exact live mapper identity, DM table immutability,
kernel staged-state correctness, real GC/p99, physical drain throughput or
permission for device teardown.

## Remaining dependency order

1. Codex independently qualifies supervisor crash/descendant containment.
2. Review trusted mapper bootstrap and exact prelaunch output identity binding.
3. Run fully joint rootless IPC/process/worker/readback tests with real direct
   workers, including all failure and process-exit paths.
4. Only then migrate production `buffer-recall.sh`, preserving all existing
   9-page, A/B staged-hit, concurrent-read, latency, discard, writer, fsync
   and cancellation assertions.
5. Obtain separate explicit authorization before virtual DM/loop/NBD/swap
   tests; only qualified, measured backend behavior can support final
   batch/strategy selection.
