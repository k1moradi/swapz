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

`nbd-pidfd-owned-session-test.py` contains 24 real-process tests,
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
a numeric-PID signal. The explicit 24-test regression runs in the rootless
NBD, teardown and combined source-only GitHub Actions suites. On an
unsupported or root host the tests skip rather than silently simulate
pidfd functionality; any reported PASS should check that they actually
executed rather than skipped.

## Parent-crash and no-descendant extension (synthetic only)

The fixed mock now arms `PR_SET_PDEATHSIG=SIGKILL` in the child before
announcing readiness, then immediately rechecks the expected parent's PID.
The PID is **compared only** and never used as a signal target. If the
parent exits before the child registers the kernel signal, the second
check fails before READY. If the parent exits afterward, Linux delivers
SIGKILL independently of control-socket EOF. The mock also normally
observes control-channel EOF while idle and exits; a deliberately
`ignore-eof` mock variant proves the parent-death mechanism works
*without* that fallback. This is a Linux-specific, test-only property.

The child also sets `PR_SET_NO_NEW_PRIVS` and a narrow seccomp BPF
filter denying `fork`, `vfork`, `clone`, `clone3`, `execve` and
`execveat` for explicitly supported x86-64/AArch64 syscall ABIs.
The filter validates the Linux audit architecture and denies x86 x32
syscalls. Unsupported architectures and filter installation failures
refuse readiness; an `attempt-spawn` test explicitly observes
`EPERM` for fork and executable replacement. This demonstrates
**no descendants from the fixed mock after filter installation**, not
a secure general-purpose process sandbox or containment for an
arbitrary real NBD executable.

A separately launched crash-owner helper passes the exact test child's
pidfd to an independent observer over AF_UNIX `SCM_RIGHTS`, then dies
via `os._exit` before READY, immediately after READY, or while idle.
The observer polls the retained pidfd for **that exact child** and
uses pidfd-only SIGKILL for any emergency recovery. It never signals
by a reusable PID or infers a child exit merely from controller death.

On a failed SIGTERM *and* failed SIGKILL / bounded wait, the owner
retains the pidfd instead of closing its only stable process identity.
A later `close()` can retry pidfd-only termination/reaping; backing
cleanup always remains false. All crash-injection tests operate on
fixed rootless Python mock processes only.

## Still required before any actual NBD benchmark

- Independently attest the real server binary and arguments, exact NBD
  device association, startup preflight, block-device ownership and
  kernel session identity; the mock nonce is **not** cryptographic identity
  against a compromised child.
- Prove parent-crash and descendant containment for an independently
  authenticated **real NBD server**, not only the fixed rootless mock.
  Its interpreter, inherited descriptors, executable and kernel session
  may differ from the mock. No real NBD client/disconnect semantics
  are exercised here.
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
