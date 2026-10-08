# V2.2 proposed direct-`dd` launch gate

**Status:** role admission is connected to the pidfd service API behind an
explicit trusted-configuration gate. The service CLI and default service
configuration still admit only the fixed `sleep` and `exit` test workers. No
production `buffer-recall.sh` integration or real mapper I/O is enabled.

The IPC form is role-only:

```json
{"id": 1, "op": "launch", "command": "recall-dd", "role": "writer"}
```

Only the trusted in-process bootstrap may construct a
`RecallDDLaunchGate` and pass it to
`SupervisorControlService(enable_direct_dd=True, recall_dd_gate=...)`. The
normal `--fd` CLI calls the service with its default configuration, so an IPC
caller cannot turn this mode on. A separately reviewed launcher/bridge change
is required before any fixture can enable it.

The service accepts no caller-supplied executable, argv, environment, working
directory, numeric PID, mapper name, input path, or output path. Extra fields
are a protocol error. The fixed `sleep` and `exit` test workers remain
unchanged.

## Exactly approved roles

The policy allows each role once, requires `writer` before any reader, and
permanently closes role admission after a rejected role or identity check.
The concurrent A/B phase must still launch `a2` and `b2` before waiting for
either; that sequencing remains in the separate recall I/O plan.

| Role | Direct `dd` arguments after descriptor binding |
| --- | --- |
| `writer` | `if=/proc/self/fd/<source-fd> of=/proc/self/fd/<mapper-fd> bs=4096 count=9 oflag=direct conv=notrunc status=none` |
| `a` | `if=/proc/self/fd/<mapper-fd> of=/proc/self/fd/<output-fd> bs=4096 skip=0 count=1 iflag=direct status=none` |
| `b` | Same read form, `skip=4`, output `read-b` |
| `a2` | Same read form, `skip=0`, output `read-a2` |
| `b2` | Same read form, `skip=5`, output `read-b2` |

`RecallDDLaunchGate` pins these resources before a role is admitted:

1. It walks the absolute fixture path one directory component at a time with
   `O_NOFOLLOW`, retains the directory descriptor, and requires a private
   directory owned by the service UID.
2. It opens `pages.bin` relative to that directory with `O_NOFOLLOW`, then
   retains and checks a single-link regular-file descriptor of exactly
   36,864 bytes. It rechecks that the directory path and source entry still
   identify the pinned objects before each role.
3. The trusted bootstrap opens the grammar-checked
   `/dev/mapper/swapz-v22-recall-...` path with `open_test_mapper_fd()`. The
   helper pins the block-device descriptor and verifies the descriptor's
   major/minor resolves through sysfs to the exact DM name. The IPC caller
   never provides this name or descriptor. The mapping and its table must
   remain exclusively controlled by the test fixture while the service runs.
4. It opens a fixed trusted `dd` executable path, checks the pinned inode is
   an executable ELF owned by root or the service UID and not writable by
   group/other, then launches by `/proc/self/fd/<executable-fd>` rather than
   resolving `dd` through `PATH`.
5. Reader outputs are created relative to the retained fixture directory
   using `O_CREAT|O_EXCL|O_NOFOLLOW`. A stale regular file, FIFO, hardlink or
   symlink makes admission fail. The generated `dd` argv names the inherited
   output descriptor, so replacing the directory entry after admission does
   not redirect the worker's write.

The supervisor's direct-launch extension requires the exact proc-fd
executable path, a close-on-exec executable descriptor, and an explicit list
of close-on-exec descriptors to pass. It starts the child behind the existing
startup gate, retains the pidfd before releasing the gate, closes every other
child descriptor in strict mode, and makes only the requested input/output
descriptors inheritable in the forked child immediately before `execve`.
Parent descriptors remain close-on-exec. The direct child is `dd` itself;
there is no shell or background Bash wrapper. All stop signals still use the
retained pidfd.

When every registered worker is reaped, `stop_all` closes the gate's retained
source, mapper, executable and output descriptors. Any close failure is
reported as a lifecycle failure and permanently denies cleanup authorization.
An unreaped worker prevents descriptor cleanup and device cleanup
authorization. The existing full stop-report reconciliation, successful
shutdown, and observed zero service exit requirements remain unchanged.

## Boundary and limitations

The descriptor-based argv removes the pathname replacement race for the
source, mapper and output object between admission and worker `open()`. A
path-only check cannot provide this guarantee; the older
`RecallDDAllowlist.admit()` planner remains only a command-description API.

The pinned source inode can still be modified in place by another process
with the same UID. The fixture must keep the private directory and source
under exclusive trusted ownership and retain an independent expected-data
reference. The fd does not freeze the DM table: a privileged actor could
reload or otherwise alter a mapping while it is open. The fixture must own the
test mapping and prohibit concurrent table changes.

The service mode is not exposed by the CLI and the current rootless tests
never call `open_test_mapper_fd()`, open `/dev/mapper`, or execute `dd`. The
role-level service tests use a synthetic regular-file descriptor as the
mapper and a fake supervisor that captures argv and descriptor lists. The
pidfd descriptor pass-through itself is tested with a short-lived Python
child, not with a block device.

A pidfd identifies only the direct `dd` child. It does not contain
grandchildren, automatically kill a worker after supervisor crash, or prove
that the kernel stopped I/O after the service disappears. GNU `dd` is
expected to be a direct non-forking worker, but this behavior and the exact
binary must be reviewed for the target environment. A service crash or lost
response always means preserve backing; it is not a cleanup authorization.
Before production recall integration, an independently owned cgroup or
equivalent containment is still required if any I/O-producing descendants
are possible.

## Source-only qualification

Run `python3 tests/runtime/recall-dd-allowlist-test.py -v` for the path-only
planner and descriptor-bound gate cases, and the service regression for the
explicit role mode. Tests cover all five exact role vectors, role ordering,
failure latching, file and directory replacement, stale output types,
executable identity, fd acquisition/closure errors, fake-supervisor startup
failure, worker failure, and default-mode rejection. They do not validate GNU
`dd` behavior through `/proc/self/fd`, DM open semantics, staged recall,
backing cleanup, or production process containment.

The existing production recall fixture still uses Bash background jobs and
numeric-PID teardown. This work does not eliminate that race.
