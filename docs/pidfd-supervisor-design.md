# Gated pidfd supervisor prototype

## Status and scope

`tests/runtime/test-child-supervisor.py` is a rootless prototype. It is not
connected to `buffer-recall.sh`, the pressure fixtures, Device Mapper, loops,
swap, or block devices. Its regression suite combines short-lived subprocesses
created solely by the tests with syscall-boundary fakes for failure cases.

The prototype owns and reaps direct children. Its public API returns an opaque
string handle. Callers do not signal a worker by PID, and the implementation
has no numeric-PID signal fallback. Pinned-executable launches opt into the
Linux process-containment filter described below; the ordinary `sleep` and
`exit` test commands retain their existing behavior.

## Launch and identity protocol

For each launch, the supervisor:

1. Validates the command and allocates a unique, nonnumeric opaque handle
   before creating a child.
2. Creates a start-gate pipe and a close-on-exec exec-error pipe.
3. For a contained launch, opens a pidfd for the supervisor itself, then
   forks a direct child. Before it blocks on the gate, the child sets
   `PR_SET_PDEATHSIG(SIGKILL)`, checks that the inherited supervisor pidfd is
   still live, and verifies `getppid()` still matches the pre-fork parent.
   The pidfd check prevents a recycled numeric parent PID from satisfying
   that identity check. The child then sets `PR_SET_NO_NEW_PRIVS` and installs
   a seccomp filter. It cannot execute the requested worker command yet.
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
never released. If the supervisor pidfd cannot be opened, no child is created.
If the worker pidfd acquisition fails after fork, the supervisor aborts the
gated child and waits for the direct child using `waitpid` only. `waitpid`
is used to reap a child owned by this supervisor; it is never used to signal.
If that child cannot be confirmed reaped, the raised `SupervisorError` sets
`preserve_required=True`. There is no PID-only fallback.

For pinned executable launches, containment setup must complete before the
parent releases the start gate. On x86_64 and aarch64 the inherited seccomp
filter rejects `fork`, `vfork`, and `clone` calls that create another process;
`clone3` returns `ENOSYS` so a runtime may fall back to the filtered `clone`
interface. `CLONE_THREAD` is allowed for utilities that use threads, since
threads remain in the same thread group and are killed with the direct worker.
The filter is installed only on little-endian x86_64 and aarch64, matching the
classic-BPF syscall-argument loads and audited syscall-number tables. Other
byte orders and architectures fail closed. The filter also denies attempts
to clear `PR_SET_PDEATHSIG`, credential
changes that Linux can use to clear the parent-death setting, namespace
changes, and legacy AIO/io_uring context creation. The latter interfaces are
not needed by the fixed synchronous `dd` roles. The filter is inherited across
`execve` and cannot be removed by the worker. Unknown architectures or failure
to install either mechanism fail before the gate opens. These
containment requirements apply to pinned executable launches; unpinned test
commands are not advertised as crash-contained.

The initial `execve` must enter the trusted, fixed direct worker. Classic
seccomp cannot distinguish that first exec from a later exec by the same
process. The allowlisted GNU `dd` role is expected not to execute another
program; admitting any worker that can perform a later set-user-ID or
file-capability exec would need a stronger launcher design because Linux may
clear `PR_SET_PDEATHSIG` on that transition. No generic executable or shell
worker is admitted by the service.

The implementation uses `os.pidfd_open()` and
`signal.pidfd_send_signal()`. Those Python APIs were added in Python 3.9;
`pidfd_open` requires Linux 5.3 or later, so Linux 5.3 is the effective
minimum for ordinary pidfd supervision. Opt-in block-mapper launches also
require executable memfd support (`MFD_EXEC`, Linux 6.3 or later) and the
required file seals; if the kernel or Python runtime cannot provide them, that
launch mode is refused. The lower-level `pidfd_send_signal` syscall appeared
earlier, in Linux 5.1.
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

## Containment guarantees and limits

The pidfd still identifies and signals one direct child, but pinned executable
launches add two independent controls around it. `PR_SET_PDEATHSIG(SIGKILL)`
terminates the direct worker if the single-threaded supervisor exits. The
seccomp filter prevents the worker from creating a separate process that could
outlive the pidfd-owned thread group, and prevents the worker from clearing
the parent-death setting or changing credentials to clear it. A worker can use
threads; those threads share the direct process lifetime. The gate and
parent-identity check cover the fork-to-pidfd and parent-death setup windows:
the command is never released before the pidfd exists and containment setup
has succeeded.

The service must still treat any lost connection, crash, timeout, malformed
response, or nonzero service exit as `preserve_backing`. Parent-death cleanup
is a last-resort stop mechanism, not a success attestation. If the service
crashes, there is no final error-free stop report, so the caller cannot
authorize device teardown even if an observer later sees the worker exit.
The rootless crash tests cover supervisor exit before pidfd acquisition, after
pidfd acquisition but before gate release, and after exec but before READY
delivery. They use only test-created workers and temporary files.

This is process-tree containment for a narrowly controlled direct executable,
not proof that kernel block I/O has drained. An abrupt worker kill can occur
while a synchronous I/O call is in progress; no real DM mapper or in-flight
BIO behavior has been tested here. Production cleanup must retain the backing
stack after abnormal service exit and must separately establish safe mapper
removal and lower-device quiescence before any physical or disposable backing
is detached. No cgroup delegation is assumed or required by this prototype.

Production recall integration must not launch `bash -c`, a background shell
function, or another wrapper that starts `dd` and returns before `dd` exits.
The direct worker must remain the only I/O-producing process, and the service
must retain its pidfd through wait/reap. The filter is limited to x86_64 and
aarch64; unsupported architectures or unavailable seccomp/PDEATHSIG support
deny launch rather than falling back.

## Rootless IPC control service

`tests/runtime/test-child-supervisor-service.py` adds a single-threaded control
loop around `GatedPidfdSupervisor`. It accepts one inherited private
`AF_UNIX/SOCK_STREAM` file descriptor with `--fd`; the socket descriptor is
marked close-on-exec before any worker launch. The controller owns the other
socketpair endpoint. The service does not create or remove DM mappings, loops,
swap entries, or backing files. Its `cleanup_after_stop()` callback returns an
in-memory marker only.

The default command allowlist is deliberately limited to:

```text
launch {command:"sleep", duration_ms:0..5000}
launch {command:"exit", code:0..125}
wait   {handle:<opaque>, timeout_ms:0..60000}
stop_all {handles:[<opaque>, ...]}
shutdown
```

The service translates `sleep` and `exit` into fixed Python worker programs.
The wire API has no PID, `argv`, shell, working-directory, environment, or
device-path field. It passes a small fixed environment to workers. The service
class also has an explicit in-process `enable_direct_dd=True` option that
requires a trusted `RecallDDLaunchGate`. It accepts only `command="recall-dd"`
with one of the five fixed `role` strings. The normal `--fd` CLI does not pass
that option or construct a gate, so its direct-dd mode remains disabled; a
future trusted launcher and its bridge/API contract need separate review
before opting in.

The descriptor-bound role gate pins the private fixture directory and source,
the exact test DM descriptor, and fixed readback outputs. It returns
`/proc/self/fd/N` arguments plus an explicit descriptor pass list. The trusted
bootstrap must supply an expected executable SHA-256 from an independent
package or deployment trust source; hashing a binary and then trusting that
same result would not establish identity. For block-mapper launches, the gate
copies the digest-verified executable into an executable memfd and applies
write, grow, shrink, seal, and exec seals. The worker executes that immutable
snapshot, so a pathname replacement or later in-place update cannot change
the bytes after verification. If executable memfd support or required seals
are unavailable, block-mapper admission fails closed. The prototype checks
byte identity; the trusted bootstrap must ensure that its expected hash is
for the intended GNU `dd`. The current host's `/usr/bin/dd` is uutils
coreutils, so no GNU `dd` identity claim is made from these tests.

`GatedPidfdSupervisor.launch()` executes the pinned descriptor without PATH
search, keeps selected descriptors close-on-exec in the parent, passes only
those descriptors in the child, and closes unlisted child FDs before exec.
The child remains blocked until its pidfd has been retained and containment
has succeeded. The service still owns the direct child and all stop signals
use that retained pidfd.

This is admission and launch preparation, not production recall integration.
Rootless role-policy tests use synthetic files and a fake supervisor; the
separate `recall-dd-worker-integration-test.py` executes the host's pinned
`/usr/bin/dd` against temporary regular files only. Neither test opens
`/dev/mapper`. The service CLI's `sleep`/`exit` allowlist remains its default.
The trusted bootstrap must still ensure the DM descriptor identifies the
exact fixture mapping and prevent concurrent DM table changes. The fixture
source file can be changed in place by another same-UID process, so the fixture
must retain an independent expected-data reference and exclude concurrent
mutation.

A pidfd alone does not contain descendants. Here, pinned launches add
`PDEATHSIG` and seccomp controls, but the implementation still does not test a
real mapper, establish in-flight block-I/O drainage, or provide a cgroup
fallback. A broken service, lost response, unconfirmed reap, fd-close failure,
or abnormal process exit always requires preserving backing. The direct-dd
CLI remains disabled; enabling it requires a separately trusted bootstrap and
review of mapper identity, the expected GNU `dd` digest, and runtime teardown
behavior.

### Wire framing and session rules

Each request and response is a four-byte unsigned network-order payload length
followed by one UTF-8 JSON object. Payloads are limited to 4096 bytes. Every
request contains a strictly increasing positive integer `id` and an `op`.
Duplicate JSON keys, non-finite JSON constants, repeated or out-of-order IDs,
unknown fields, malformed JSON, truncated frames, and unsupported operations
are rejected. The service sends a bounded deterministic error response when
possible, closes the session, and attempts to stop/reap its registered direct
children. Each complete frame has a finite read and write deadline; partial
frames use the same deadline. The client applies its own deadline and treats
EOF, timeout, malformed response, or mismatched request ID as
`preserve_backing`. Its API distinguishes `ProtocolFailure` from
`SupervisorUnavailable`; both permanently deny cleanup authorization for that
session.

Every response carries `cleanup_allowed` and `preserve_backing`, with exactly
one true. `launch` returns only an opaque handle after the supervisor's pidfd
gate and exec handshake. `wait` accepts only a handle previously returned by
that session and a bounded timeout. A timeout reports `running` and cannot
authorize teardown. A natural nonzero exit is a lifecycle error even after
the child has been reaped.

`stop_all` permanently closes launch admission and passes the supplied handle
list to `cleanup_after_stop()`. The client retains every opaque handle from a
valid `ready` response and checks the complete `stop_all` report before it
records even provisional authorization. A successful report must have the
expected top-level verdict fields, an empty report error list, and exactly one
well-formed, reaped, error-free worker row for every handle returned by launch.
Missing, duplicate, unknown, or changed handles; malformed row types; an
unreaped row; a worker error; a report error; or contradictory verdict fields
permanently deny cleanup. The only service callback remains an in-memory
marker. Repeated `stop_all` calls still make a best-effort reap pass but latch
failure and cannot produce a new authorization.

The required sequence is one or more successfully tracked launches (or an
empty worker set), one complete `stop_all`, a successful `shutdown`, and an
observed zero exit from the exact service process launched for this control
session. When the client is constructed with that service's `subprocess.Popen`
object, `confirm_service_exit(exit_code)` polls it and requires the observed
return code to match the value supplied by the caller. When no Popen object is
bound, the caller must pass only the exact result returned by waiting for this
service process; a fabricated code is outside the client API contract. Cleanup
authorization is monotonic: a protocol,
transport, launch, wait, stop, shutdown, inventory, or exit failure cannot be
cleared by a later positive response. A shutdown attempted before a clean
`stop_all` permanently denies cleanup; best-effort stopping may still proceed
to reap children, but the service exits unsuccessfully. (The client deadline
defaults to 75 seconds, longer than the 60-second maximum natural wait
request.) The caller must preserve backing after a service crash, disconnect,
broken pipe, timeout, invalid or contradictory response, nonzero exit, or any
lifecycle failure, even if the service logs that it recovered and reaped its
workers internally. Requests queued after shutdown are not processed; the
service closes the channel.

The service loop and the fork-based supervisor require the service process to
remain single-threaded with default `SIGCHLD` handling. The supported baseline
is Linux 5.3 or newer with Python 3.9 or newer exposing `os.pidfd_open()` and
`signal.pidfd_send_signal()`. If pidfd support is absent or acquisition fails,
there is no numeric-PID signaling fallback and no cleanup authorization.

Pinned worker launches now install parent-death and process-creation controls,
but the control service still does not make supervisor crashes a cleanup
success. If the service dies, the worker receives `SIGKILL` and the client
must preserve the DM/loop stack because there is no final successful
all-reaped attestation. A pidfd and seccomp do not establish that submitted
kernel I/O has drained, and no real mapper or lower-device teardown has been
tested. Production workers must be the direct pinned executable, without a
shell wrapper or I/O-producing descendants.

## Proposed `buffer-recall.sh` migration

The current fixture tracks `WRITER`, `PIDA`, and `PIDB` as Bash numeric job
PIDs. The writer is a direct background `dd`, while the two parallel readers
are background Bash function subshells that each run `dd` and `cmp`. The latter
are unsafe to supervise as one PID because the shell subshell can exit or be
signaled while a child `dd` continues doing mapper I/O.

The integration should be a separate reviewed change with these steps:

1. Add a separately reviewed trusted launcher/adapter that creates the private
   socketpair, starts this service with the service endpoint as its inherited
   `--fd`, and gives the controller endpoint to the fixture's persistent
   Python IPC adapter. Keep both alive until EXIT cleanup finishes. Bash sends
   only the documented bounded requests through that adapter and stores opaque
   handles; it never receives worker PIDs. The normal service CLI must remain
   limited to `sleep`/`exit`; direct-`dd` role admission may be enabled only by
   a trusted in-process bootstrap that binds the exact mapper, fixture, and
   independently trusted GNU `dd` digest. Do not expose a generic `argv` or
   signal operation.
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

Run the rootless source checks with:

```sh
python3 -m py_compile tests/runtime/test-child-supervisor.py \
  tests/runtime/test-child-supervisor-regression.py \
  tests/runtime/test-child-supervisor-service.py \
  tests/runtime/test-child-supervisor-service-regression.py \
  tests/runtime/recall-dd-allowlist.py \
  tests/runtime/recall-dd-allowlist-test.py \
  tests/runtime/test-child-containment-regression.py
python3 tests/runtime/test-child-supervisor-regression.py -v
python3 tests/runtime/test-child-supervisor-service-regression.py -v
python3 tests/runtime/recall-dd-allowlist-test.py -v
python3 tests/runtime/test-child-containment-regression.py -v
python3 tests/runtime/recall-dd-worker-integration-test.py -v
```

The real-process tests create only short-lived children for this suite. The
failure injection tests use syscall fakes and numeric placeholder PIDs; they
do not signal those placeholder PIDs or touch any device. The containment
regressions exercise worker termination and denied fork attempts on this host,
but they do not validate production recall teardown, mapper identity, or
kernel/block-device I/O behavior.
