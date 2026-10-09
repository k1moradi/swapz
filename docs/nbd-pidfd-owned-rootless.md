# V2.2 rootless pidfd-owned NBD-like server process model

**Status: rootless, fixed mock executable and no-device qualification only.**
This is NOT the live NBD benchmark controller. In particular,
`streaming-benchmark.sh` continues to reject `SWAPZ_BENCH_BACKEND=nbd`
before allocation or attachment, and its teardown helper continues to
preserve NBD backing without signaling an unowned process.

## Problem and intended trust boundary

The earlier streaming benchmark used `NBD_PID=$!` and numeric PID liveness
checks and SIGTERM. The process can exit between `kill -0` and
`kill -TERM`, allowing PID reuse. The fail-closed live NBD disablement
removed the unsafe path but left no dedicated test of stable server-process
identity.

The new test-only `nbd-pidfd-owned-session.py` demonstrates a safer
building block without any device operation. It starts one **fixed Python
test program**, `nbd-pidfd-owned-mock-child.py`, using an exact
`subprocess.Popen` object and inherited AF_UNIX `SOCK_SEQPACKET`
descriptor. The fixture path is private and owned, and no command, device
or executable path is accepted over IPC.

The owner:

1. Rejects root execution, unsupported Linux pidfd APIs, non-private
   fixture directories and unsupported test fault modes before launch.
2. Probes pidfd support, starts its direct test-owned child, then calls
   `os.pidfd_open` while the child remains Popen-owned and unreaped. The
   unreaped child cannot have its PID recycled at this stage.
3. Sends a session-specific random nonce over the inherited socket;
   verifies a single exact `READY <nonce>` packet within a short timeout;
   and checks the child has not already exited.
4. Retains the pidfd throughout the controlled running state.
5. Initiates shutdown exclusively via
   `signal.pidfd_send_signal(pidfd, SIGTERM)`, then uses the actual
   owning `Popen.wait(timeout=...)` for the exact child.
6. Grants **process-exit proof only** when that wait returns zero.
   `kernel_nbd_disconnected`, `dm_io_drained` and
   `backing_cleanup_authorized` remain fixed `False`.
7. On timeout, failed signal, malformed readiness, wrong exit status or
   interrupted ownership, denies the session. When a retained pidfd is
   available, it terminates the exact child using pidfd SIGKILL and performs
   a bounded reap. A process that cannot be verified as reaped is a
   preservation/diagnostic case; numeric-PID fallback is forbidden.
8. If pidfd acquisition fails *after* spawning the fixed test child,
   closes the owned socket so that the child exits on handshake EOF. Its
   completed return code must still be directly observed. No signal by
   numeric PID is permitted.

The rootless mock child installs its SIGTERM handler **before** announcing
readiness, avoiding a readiness-to-handler installation race.

## Rootless tests and scope

`nbd-pidfd-owned-session-test.py` contains 19 real-process tests,
including: clean pidfd shutdown/reap; one-shot use; context exit before
shutdown; wrong nonce; readiness EOF; slow/absent readiness; SIGTERM
ignored; nonzero exit; spontaneous exit after READY; pidfd signaling error;
missing pidfd support before spawn; pidfd-open failure **after spawn**;
invalid worker mode and path; symlinked/non-private fixture directory;
private retained diagnostics; close idempotence; and source-level denial
of direct NBD/device operations or PID signal fallbacks.

The tests launch a fixed synthetic Python process and signal **only that
test-owned process through its pidfd**. They never attach NBD, call
`dmsetup` or `losetup`, enable swap, create kernel resources, or send
a numeric-PID signal. The explicit 19-test regression runs in the rootless
NBD, teardown and combined source-only GitHub Actions suites. On an
unsupported or root host the tests skip rather than silently simulate
pidfd functionality; any reported PASS should check that they actually
executed rather than skipped.

## Still required before any actual NBD benchmark

- Independently attest the real server binary and arguments, exact NBD
  device association, startup preflight, block-device ownership and
  kernel session identity; the mock nonce is **not** cryptographic identity
  against a compromised child.
- Bind the server and its descendants to a controlled lifetime. These
  mock tests do not establish parent-crash descendant containment or
  real NBD client/disconnect semantics.
- Verify stop of all kernel NBD requests, complete session disconnect,
  error-free read/write completion and exact device detach independently
  of the server's exit.
- Preserve backing until the DM suspend/drain and normal-removal policy
  is satisfied and every kernel NBD/loop dependency is confirmed absent.
- Obtain a separate explicit operator authorization for a disposable
  virtual-device test. Merely passing rootless pidfd mock tests must
  **never re-enable** `SWAPZ_BENCH_BACKEND=nbd` or approve cleanup.
- Run three or more genuine repeat samples at all batch sizes, sufficient
  swap-in p99 samples and independently measured lower-device sector
  drain before evaluating V2.2 performance; source-only fake data
  supplies no throughput winner.

This module deliberately exports no general pidfd process-terminator CLI,
no user-specified PID/argv, and no cleanup authorization API.
