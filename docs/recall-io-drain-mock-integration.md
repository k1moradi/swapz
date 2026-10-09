# Rootless V2.2 drain evidence orchestration and NBD shutdown hold

**This is mock qualification, not a kernel I/O-drain test.** Neither
`recall-io-drain-orchestrator.py` nor its regression invokes
`dmsetup`, `losetup`, `swapon`, `swapoff`, kernel ioctls,
fio, NBD attachment or module operations.

## Integrating Codex's state machine without weakening it

`recall-io-drain-orchestrator.py` imports the original
`DMIODrainPolicy` unchanged. One explicit
`RootlessMockDrainSession` binds the exact tuple of upper-to-lower
synthetic DM names, loop identifier, test-owned private regular-file
marker and an exact `SyntheticFixtureOps` instance. Arbitrary
IPC-supplied evidence or `cleanup_allowed=True` values are not
supported.

The simulated operation provider derives exact event dictionaries from
fabricated in-memory state: close admission, reconcile five unique
handles, stop synthetic test swap, ordinary suspend, close descriptors,
read open/holder counts, remove each upper-to-lower mapping, re-inventory
the absent mapping, check lower dependency holders, and detach the
synthetic loop. **Nothing** in that sequence proves a real Linux kernel
has drained pending block I/O.

Every event is fed immediately into Codex's state-machine validator.
Missing, extra, contradicted, failed or out-of-order evidence raises and
permanently denies the mock session. The next operation is not attempted
after any failure. No device operation is triggered at any point.
An adversarial regression injects failure at every one of the 15 ordered
operation stages; repeated attempts cannot recover after a denial.
Other tests vary the worker handle inventory, swapoff, noflush/suspend,
DM identity, descriptor closure, open counts, holders, false-positive
removal, upper success/lower failure, loop detach and marker identity.

Only when the exact final policy stage has passed can the session
consider synthetic backing deletion. A separate marker check verifies
private ownership, regular single-link inode and the *same* originally
bound device/inode. If the marker has been swapped, even a positive
mocked state-machine decision cannot unlink it. The implementation
uses `Path.unlink` only for that private test marker. A failed marker
check latches a session-level denial; it does not pretend the earlier
positive policy history had been revoked.

The mock operation provider is deliberately not a production evidence
collector. The existence of a Python `True` in its synthesized receipt
cannot establish kernel suspend, DM table exclusivity or physical-media
durability. Real fixture integration would need independent trusted
observations, open/holder inventory and the separately controlled
privileged mapper owner under development.

## Source-only qualification

Both mandatory rootless GitHub workflows now run Codex's original
eight drain-policy tests **and** the additional synthetic orchestrator
regressions, with Python compilation and bounded subprocess timeouts.

The teardown workflow additionally runs the existing NBD and streaming
teardown mocks. The source-only NBD workflow continues to run userspace
NBD socket protocol selftests with explicit mock syscall isolation.

## NBD numeric-PID shutdown disabled pending qualified ownership

Previously, `streaming-benchmark.sh` started a size-aware NBD server in
a Bash background job and saved `NBD_PID=$!`; its teardown helper then
used `kill -0`, `kill -TERM`, `ps` and `wait` by numeric PID. A
numeric PID is not an independently stable process identity. The
liveness-check-to-signal sequence can race PID reuse.

The benchmark now **rejects NBD backend mode before allocating its
temporary directory or launching any worker**. `setup_nbd` is a
defense-in-depth refusal rather than an executable unsafe launch path.
The shared teardown helper also categorically rejects NBD shutdown,
does not signal numeric PIDs and preserves backing/diagnostics even if
the test DM target has been successfully and normally removed.

This means **the opt-in NBD benchmark mode is intentionally unavailable**.
It is not a quiet behavioral change: the operator receives an explicit
nonzero exit and explanatory error. Null-blk setup retains its existing
separate control path, subject to its own safety and explicit-approval
requirements. The NBD userspace protocol selftest remains available,
without attaching devices.

Before restoring NBD support, implement and independently review a
controller that starts the *exact owned* server, keeps its pidfd or
equivalent stable ownership through shutdown, obtains a verified clean
reap, and securely binds the server to its exact disposable NBD device
and all backing dependencies. The controller must fail closed on crash,
EOF, missing pidfd, shutdown error or timeout, and must never fall back
to numeric PID signaling. Model this with owned temporary-file workers
first, and do not issue actual NBD commands without separate explicit
authorization.

## Unqualified live gates

The real DM lifecycle still requires independently trusted GNU
coreutils executable provenance, exclusive privileged mapper ownership,
an ordinary and observed kernel DM suspend/drain, correct normal removal
and verified absence at each layer, and original swap/backing integrity.
The workload's actual p99 and physical-throughput plateau are not
established. No virtual-device or physical-device campaign has been
authorized or performed by this source-only work.
