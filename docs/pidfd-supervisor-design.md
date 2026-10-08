# Gated pidfd supervisor prototype

## Status and scope

`tests/runtime/test-child-supervisor.py` is a rootless prototype. It is not
connected to `buffer-recall.sh`, the pressure fixtures, Device Mapper, loops,
swap, or block devices. Its regression suite combines short-lived subprocesses
created solely by the tests with syscall-boundary fakes for failure cases.

The prototype owns and reaps direct children. Its public API returns an opaque
string handle. Callers do not signal a worker by PID, and the implementation
has no numeric-PID signal fallback.

## Launch and identity protocol

For each launch, the supervisor:

1. Validates the command and allocates a unique, nonnumeric opaque handle
   before creating a child.
2. Creates a start-gate pipe and a close-on-exec exec-error pipe.
3. Forks a direct child. The child closes its unused pipe ends and blocks on
   the gate; it cannot execute the requested worker command yet.
4. Opens a pidfd for that unreaped child and stores it in the supervisor's
   private worker record.
5. Sends the one-byte start token through the gate. If this fails, it sends an
   abort token where possible and stops/reaps the child; it does not return a
   usable handle.
6. Waits for the exec-error pipe to report either an exec error or close on
   successful exec. Only then does `launch()` return the opaque handle.

The READY boundary means the command passed the exec handshake. The worker
may already be executing by the time `launch()` returns, but the pidfd was
acquired before the gate was released, so worker code cannot run without stable
identity already retained. Tests that need to observe worker behavior wait for
an explicit worker-side marker; they do not treat READY as an application-level
readiness probe.

If Python pidfd APIs are missing, or pipe/fork/pidfd setup fails, the gate is
never released. If pidfd acquisition fails after fork, the supervisor aborts
the gated child and waits for the direct child using `waitpid` only. `waitpid`
is used to reap a child owned by this supervisor; it is never used to signal.
If that child cannot be confirmed reaped, the raised `SupervisorError` sets
`preserve_required=True`. There is no PID-only fallback.

The implementation uses `os.pidfd_open()` and
`signal.pidfd_send_signal()`. Those Python APIs were added in Python 3.9;
`pidfd_open` requires Linux 5.3 or later, so Linux 5.3 is the effective minimum.
The lower-level `pidfd_send_signal` syscall appeared earlier, in Linux 5.1.
See the [Python `os.pidfd_open` reference](https://docs.python.org/3.12/library/os.html#os.pidfd_open),
the [Python `signal.pidfd_send_signal` reference](https://docs.python.org/3.11/library/signal.html#signal.pidfd_send_signal),
and the Linux [`pidfd_open(2)`](https://man7.org/linux/man-pages/man2/pidfd_open.2.html)
and [`pidfd_send_signal(2)`](https://man7.org/linux/man-pages/man2/pidfd_send_signal.2.html)
manual pages.

Because this prototype uses `fork()` followed by `pidfd_open()`, it runs only
from the sole Python main thread and refuses a non-default `SIGCHLD`
disposition. The parent must remain the only reaper for its children until
each pidfd is opened and each child is explicitly waited. Production code must
preserve that ownership rule; another thread or native component that reaps
children behind the supervisor would invalidate the child-identity assumption.
An atomic `clone3(CLONE_PIDFD)` launcher could remove the post-fork acquisition
window, but it would need a small native binding and is not used here.

## Stop, reap, and cleanup contract

`stop_all(handles)` validates the caller's handle list and processes every
registered worker, even if a handle was accidentally omitted or an earlier
worker has a signal or wait failure. Omitted, unknown, duplicate or malformed
handles make the report fail closed; an omitted worker is still stopped and
reaped, but the callback remains denied so the caller has to resolve the
tracking error:

```text
for each known handle:
    if already reaped: report its saved status
    else if pidfd says exited: waitpid the owned child and reap it
    else:
        send SIGCONT through retained pidfd
        send SIGTERM through the same pidfd
        wait up to term_grace
        if still not reaped and escalation is enabled:
            send SIGKILL through the same pidfd
            wait up to kill_grace
    close pidfd exactly once, and only after reap

cleanup_allowed = every handle was known and unique
                  AND every direct child was reaped
                  AND no inspection, signal, wait, or close error occurred
                  AND no worker exited unsuccessfully before stop was requested
```

`cleanup_after_stop(handles, callback)` first closes worker-launch admission,
then invokes the callback only when `cleanup_allowed` is true. If a process
remains unconfirmed or unreaped, its pidfd stays open in the supervisor and
cleanup is denied. A signal failure
continues through the remaining stop/reap attempts, but it still denies the
callback even if escalation later reaps that worker. A worker that naturally
exits nonzero is reported as failed and also denies cleanup. A nonzero status
caused by the supervisor's requested TERM/KILL sequence is reported in the
result but does not by itself mean a worker remained active.

The supervisor does not authorize device teardown merely because a process
looks absent in `/proc`. The only positive cleanup decision is based on direct
child reaping and error-free lifecycle operations.

## What this does not contain

A pidfd refers to one process. It does not automatically stop grandchildren,
children forked by a worker, or background work started by a shell wrapper.
Reaping the direct child is therefore sufficient only if the launched command
does not leave I/O-producing descendants behind.

Production recall integration must not launch `bash -c`, a background shell
function, or another wrapper that starts `dd` and returns before `dd` exits.
The safest first integration is an allowlist of direct executables and
arguments (`dd` for writer/read transfers) plus synchronous comparison and
timing in the parent test harness. If a worker must create descendants, place
the whole worker tree in a test-owned cgroup and confirm it is empty before
device cleanup; direct-child pidfds alone cannot prove that tree is quiet.

The prototype also does not contain a worker if the supervisor itself crashes
or is killed. A production control service must treat a lost supervisor
connection as a cleanup failure and preserve the DM/loop stack. A later
integration can add a parent-death signal and/or a fixture-owned cgroup, but
must test those mechanisms independently; they are not part of this prototype.

## Proposed `buffer-recall.sh` migration

The current fixture tracks `WRITER`, `PIDA`, and `PIDB` as Bash numeric job
PIDs. The writer is a direct background `dd`, while the two parallel readers
are background Bash function subshells that each run `dd` and `cmp`. The latter
are unsafe to supervise as one PID because the shell subshell can exit or be
signaled while a child `dd` continues doing mapper I/O.

The integration should be a separate reviewed change with these steps:

1. Start one single-threaded Python supervisor control process for the fixture.
   Keep it alive until the fixture's EXIT cleanup has completed. Bash sends
   commands and receives opaque handles over a private inherited pipe or
   Unix-domain socket; it never receives worker PIDs. The control protocol
   must validate request IDs and handles and must not expose arbitrary
   signaling.
2. Replace the writer's `dd ... &` with `launch` of the direct `dd` argv. Keep
   its handle in a list immediately after a successful launch.
3. Preserve the first A and B recall timing points by launching each direct
   read `dd`, recording monotonic start/end values in the fixture, waiting for
   that handle, then running `cmp` in the fixture. Pre-create each expected
   page from `pages.bin` before launching the mapper read. This removes the
   background `read_page` shell functions and their hidden `dd` descendants.
4. For the simultaneous A/B case, launch both direct read `dd` commands before
   waiting for either handle. Wait for and check both results, then compare
   each output with its expected page. Keep the existing wall-clock measurement
   around both waits so the concurrency assertion remains meaningful.
5. Keep every successful handle in the cleanup list even after `wait` has
   reaped it. The supervisor retains the result and makes repeat cleanup
   idempotent for already-reaped handles. On a launch exception, include its
   attached handle if one exists; if `preserve_required` is true or the
   supervisor is unreachable, do not invoke the DM/loop cleanup helper.
6. In the EXIT trap, ask the supervisor to stop/reap all tracked workers.
   Invoke `swapz_test_cleanup_dm_stack` only after an explicit all-reaped,
   cleanup-allowed response. Any worker, signal, wait, reap, descriptor-close,
   protocol, or supervisor failure leaves the backing image and diagnostic
   directory in place and returns nonzero.
7. Stop the control process only after all worker handles are resolved. Its
   shutdown response must itself confirm there are no retained unreaped
   workers before Bash may exit successfully.

The serialized first A and B reads keep their current order. The dual-read
phase still starts both reads before either wait. The writer remains active
while the fixture checks staged recall and is waited only at its current
checkpoint. This preserves the existing A/B test sequence while changing who
owns the child processes.

Before production integration, add rootless tests for the control protocol,
lost supervisor connection, launch error propagation, simultaneous reader
ordering, exact expected-data comparison, cleanup denial on every worker
failure, and the guarantee that no `dd` descendant remains. Do not infer that
the existing Bash job/PID cleanup race has been removed until that integration
is separately reviewed and tested.

## Prototype validation

Run the standalone source checks with:

```sh
python3 -m py_compile tests/runtime/test-child-supervisor.py \
  tests/runtime/test-child-supervisor-regression.py
python3 tests/runtime/test-child-supervisor-regression.py -v
```

The real-process tests create only short-lived children for this suite. The
failure injection tests use syscall fakes and numeric placeholder PIDs; they
do not signal those placeholder PIDs or touch any device. These tests do not
validate production recall teardown, descendant containment, or kernel/block
device behavior.
