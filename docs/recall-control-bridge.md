# V2.2 persistent Bash-to-pidfd control bridge (test-only)

**Status:** Rootless, test-worker-only integration prerequisite. The bridge is
not imported or sourced by production \`tests/runtime/buffer-recall.sh\`.
Numeric-PID signaling in that fixture remains an unresolved safety concern.

## Ownership

The persistent Python controller is
\`tests/runtime/recall-control-bridge.py\`. Bash runs it exactly once as a
coprocess. The bridge creates a private AF_UNIX socketpair, starts exactly one
\`test-child-supervisor-service.py\` subprocess with the inherited endpoint,
and keeps the other endpoint and the subprocess \`Popen\` object through
\`stop_all\`, \`shutdown\` and finalization. It uses
\`SupervisorControlClient(service_process=Popen)\` and
\`RecallIPCAdapter\`, preserving the same opaque handle registry throughout.

The only permitted worker programs remain the IPC service's fixed \`sleep\`
and \`exit\` test workers. Bash never sees or signals a numeric worker PID.
The controller does not accept an argv, shell command, mapper path, fd, or
direct-dd role. The standalone \`recall-dd-allowlist.py\` is not connected.

## Bash protocol

Each request is a bounded (2048-byte maximum), newline-terminated UTF-8 JSON
object with a strictly increasing positive \`id\` and one uppercase operation.
The bridge sends an initial \`bridge_ready\` reply, followed by exactly one
JSON response per request. Every reply contains \`cleanup_allowed\` and
\`preserve_backing\` as complementary Boolean fields. Request size, frame
format, duplicate JSON keys, data types, unknown fields, unknown operations
and request sequence are validated before dispatch.

| Operation | Required payload | Meaning |
| --- | --- | --- |
| \`LAUNCH_TEST\` | \`command:"sleep",duration_ms:0..5000\` or \`command:"exit",code:0..125\` | Launch one approved short-lived direct test worker; return opaque handle |
| \`WAIT\` | \`handle:<previously returned opaque>,timeout_ms:0..60000\` | Require natural successful worker exit and confirmed reap |
| \`STOP_ALL\` | No additional fields | Close admission; send *complete internally retained* handle list; require detailed all-reaped attestation |
| \`SHUTDOWN\` | No additional fields | Request clean shutdown, wait for the exact service subprocess and verify status zero |
| \`FINALIZE\` | No additional fields | Verify already-confirmed exit, close client socket without errors, then and only then report synthetic cleanup authorization |

The application-level \`STOP_ALL\` and \`SHUTDOWN\` replies **always report
\`cleanup_allowed:false\`**, even after a complete stop: Bash may remove a
synthetic backing marker only when \`FINALIZE\` returns
\`{"status":"cleanup_authorized","cleanup_allowed":true,...}\`.
\`FINALIZE\` is not idempotent. No production cleanup callback is supplied.

When a malformed request or any worker/transport/lifecycle error occurs, the
bridge emits a fail-closed \`preserve_backing\` response when possible and exits
nonzero. A malformed frame never inherits an earlier request ID. The bridge
closes its control socket and waits for best-effort service cleanup, but
**internal recovery is not cleanup authorization**. A service that cannot be
confirmed exited also requires backing preservation. No numeric PID signal
fallback is attempted.

## Bash test evidence and limitations

\`tests/runtime/recall-control-bridge-regression.sh\` launches a genuine
Bash \`coproc\` and keeps one bridge through three opaque test-worker launches,
two reader-equivalent launches before either wait, writer-handle preservation,
stop, shutdown and finalization. It separately tests a nonzero worker exit,
unplanned controller EOF and Bash's rejection of malformed/contradictory
replies. A private temporary marker is removed only after positive
finalization; failure paths retain diagnostic markers until the rootless
test harness disposes of its own test directory.

\`tests/runtime/recall-control-bridge-test.py\` adds short-lived real
socketpair/service subprocess tests and fake-client failures including
out-of-order/duplicate request IDs, unknown workers, rejected arbitrary
commands, request truncation and oversize, omitted or duplicate cleanup
handle requests, lost control before/after STOP_ALL, nonzero worker exit,
premature finalization, and simulated final descriptor-close denial.

Run \`timeout 110s bash tests/runtime/recall-control-bridge-regression.sh\`.
Both mandatory rootless GitHub workflows also run this gate alongside the
existing IPC, pidfd, recall I/O, pressure, GC, and NBD tests.

**Not proved by this gate:** safe \`dd\` execution, descriptor-bound
file/device identity, descendant containment after supervisor crash, live DM
or loop teardown, real swap, actual A/B latency, GC behavior or any
physical-storage benchmark. Production migration must separately replace
background Bash I/O and numeric-PID teardown with the reviewed direct-IO
role-only service, retaining all five handles and preserving backing if the
supervisor disappears. Future data comparisons, timed read staging, discard
and fsync must remain part of the original recall test rather than this
test-only control bridge.
