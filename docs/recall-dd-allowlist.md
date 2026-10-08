# V2.2 proposed direct-`dd` launch allowlist

**Status:** source-only design and rootless test fixture, **not** wired into the
pidfd IPC service or production `buffer-recall.sh`.

The launch policy in `tests/runtime/recall-dd-allowlist.py` is intended to be
instantiated by a **trusted fixture launcher** that already holds the private
fixture directory and test-specific DM mapper name. The IPC caller must not be
allowed to provide an arbitrary fixture root, mapper path, direct executable,
argument vector, shell string, or numeric PID.

## Exactly approved direct worker commands

After the immutable fixture paths have been bound, the following are the only
one-use roles:

| Role | Direct argv | Purpose |
| --- | --- | --- |
| `writer` | `dd if=<fixture>/pages.bin of=/dev/mapper/<test> bs=4096 count=9 oflag=direct conv=notrunc status=none` | Staged nine-page writer |
| `a` | `dd if=/dev/mapper/<test> of=<fixture>/read-a bs=4096 skip=0 count=1 iflag=direct status=none` | First Buffer A read |
| `b` | `dd if=/dev/mapper/<test> of=<fixture>/read-b bs=4096 skip=4 count=1 iflag=direct status=none` | First Buffer B read |
| `a2` | `dd if=/dev/mapper/<test> of=<fixture>/read-a2 bs=4096 skip=0 count=1 iflag=direct status=none` | Concurrent A read |
| `b2` | `dd if=/dev/mapper/<test> of=<fixture>/read-b2 bs=4096 skip=5 count=1 iflag=direct status=none` | Concurrent B read |

The controller must launch both `a2` and `b2` before waiting on either
one. Launch-before-wait ordering belongs to the separate
`recall-io-plan.py` test, not this stateless role-ordering policy.
Only the writer-before-reader condition is enforced here.

The `admit(role, proposed_argv=None)` API builds a fixed argv internally.
A caller-provided proposal, if any, must match the entire generated vector
exactly. Unrecognized roles, aliases, changed flags, duplicate role requests
and launch requests following any denied admission are rejected permanently.
This source-only API returns a descriptor of the proposed command; **it does
not execute or supervise any process**.

## Fixture-file and path restrictions

The prebound root must be an absolute, canonical, existing non-symlink
directory. The sole input is its direct child `pages.bin`, an existing
single-link regular file exactly nine 4096-byte pages in size. The root and
source inode identities are retained at policy construction and rechecked
before each role admission. Reader output paths are fixed children named
`read-a`, `read-b`, `read-a2`, or `read-b2`. Any pre-existing path,
including a dangling symlink or FIFO, is rejected. The mapper basename
must match `swapz-v22-recall-[A-Za-z0-9_-]{1,48}`, and the policy never
looks up or opens `/dev/mapper`.

**Important limitations:** path validation followed by a later worker `exec`
has a time-of-check/time-of-use window. No filesystem policy alone makes
pathname arguments to `dd` race-proof against a privileged or same-UID
adversary that can replace files after validation. A production launcher must
create, hold and lock down an owner-controlled private directory; bind the
DM mapping to a trusted setup identity; define the permitted file-descriptor
or path-open strategy; verify the output namespace; and test race behavior
at the actual spawn boundary. In-place modifications to same-inode source
contents also require the separate immutable reference/data checks.

A pidfd tracks the direct `dd` child but **does not contain descendants** or
protect against supervisor crash. The future integration must prohibit
untracked I/O descendants or prove an independently owned cgroup is empty
before DM/loop teardown. Service disconnection, unconfirmed stop/reap, or an
unverified clean service exit must preserve backing and diagnostics.

## Source-only qualification

Run `python3 tests/runtime/recall-dd-allowlist-test.py -v`.
The rootless tests verify the exact writer and four reader commands, parity
with the fixture-neutral recall I/O plan, malformed/extra arguments and path
redirection, source replacement, symlinked ancestors, FIFO/hardlinked source,
missing/truncated source, stale outputs, single-use admission and permanent
denial. They never spawn `dd`, open a mapper, or issue a swap/device command.

The live recall fixture still uses background Bash children and numeric
PID-based teardown. These tests **do not** eliminate its PID-reuse risk or
establish real staged A/B latency, data persistence, NBD, GC, or device safety.
