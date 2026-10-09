# V2.2 recall teardown I/O-drain contract

**Status: design and rootless policy model only.** No production fixture calls
this model, and no real device teardown was run. The current shared helper
removes DM mappings normally with `dmsetup remove --retry`, checks mapping
absence, and checks loop holders before normal loop detach. It does not yet
request or independently record an ordinary DM suspend before removal. The
model below is a proposed gate for a separately reviewed fixture integration.

## What process exit establishes

Successful pidfd wait/reap establishes that a registered direct worker exited
and can no longer issue new userspace syscalls through its descriptors. It is
not by itself proof that all block I/O submitted before exit has completed.
A worker killed during an I/O operation can also leave the device-side request
active while it exits. Keep the fixture admission closed, require complete
worker inventory and error-free reaping, then ask the kernel DM layer for an
independent drain barrier.

The Linux Device Mapper UAPI says `DM_SUSPEND` does not return until pending
I/O to the device has completed, and further I/O is deferred until resume.
`dmsetup suspend` without `--noflush` waits for already mapped I/O to finish;
`--noflush` explicitly avoids flushing outstanding I/O. These semantics are
documented by the [Linux DM ioctl UAPI](https://github.com/torvalds/linux/blob/master/include/uapi/linux/dm-ioctl.h#L1056-L1064)
and [`dmsetup(8)`](https://man7.org/linux/man-pages/man8/dmsetup.8.html).
This is an in-flight I/O completion guarantee at the DM boundary, not a claim
that every write has reached nonvolatile media or that a filesystem cache has
been durably synchronized.

Normal `dmsetup remove` refuses to remove an open mapped device. `--force`
replaces the table with an error target, while `--deferred` only schedules
removal after the last opener closes. Neither establishes the required
immediate normal removal and verified absence. Use neither option in this
safety path. A retryable normal remove may be attempted, but exhaustion,
timeout, ambiguous return, or a surviving mapping preserves all lower
dependencies and backing.

## Ordered evidence state machine

`tests/runtime/recall-io-drain-policy.py` models this order for a fixed stack
listed from upper mapping to lower mapping:

```text
close launch admission
  → reconcile and reap every worker
  → validate exact mapping is no longer active swap
  → for each DM mapping, upper to lower:
       ordinary suspend completed; identity still matches
       close every fixture-owned descriptor
       verify valid DM inventory, open count zero, and no holders
       normal remove succeeded; no force or deferred mode
       independently verify name, UUID and device number are absent
  → verify all DM layers are gone and exact loop holder inventory is empty
  → normal detach of exact loop; re-inventory and confirm it is absent
  → cleanup backing file
```

The model requires explicit, exact evidence fields at each transition. It
rejects missing/extra fields, wrong order, timeout, incomplete worker
inventory, swap inventory errors, unsuccessful swapoff, `--noflush`, failed
suspend, open-count/holder uncertainty, force/deferred removal, malformed DM
inventory, a reappearing mapping, loop inspection failure, or an unverified
loop detach. Any denial is sticky; later successful observations do not
restore cleanup permission. `cleanup_allowed` becomes true only after the
final normal detach and complete inventory confirmation.

The model contains no subprocess, ioctl, DM, loop, swap, or filesystem cleanup
code. A future fixture integration must independently validate each source of
evidence: worker-service attestation; complete `/proc/swaps` parsing and
swapoff result; DM ioctl/suspend return and post-state; exact DM name/UUID/dev
and table identity; DM open count; full DM inventory; sysfs holder inventory;
exact loop association; and post-detach loop inventory. Unknown or
contradictory data must stop teardown and retain diagnostics/backing.

## Limits and unresolved evidence

- A successful ordinary DM suspend is the kernel-side drain boundary for I/O
  already submitted through that mapped device. A failed or indefinitely
  blocked suspend remains a preservation case; do not continue because a
  userspace timer expired.
- Suspended devices defer later I/O. The fixture must close admission, reap
  every owned worker, disable/verify test swap, and rule out other openers
  before removal; otherwise the mapping must remain suspended with backing
  retained for diagnosis.
- DM name, UUID, major/minor and a table fingerprint identify observed state.
  They do not lock the table against a privileged concurrent reload. A
  separately controlled fixture owner must hold exclusive lifecycle control
  from mapping creation through verified removal. The owner must be the only
  authority able to mutate that disposable table.
- DM open count and holder lists are corroborating checks, not substitutes
  for the suspend and successful normal remove. Inspection failures never mean
  “zero.”
- The suspend/remove/absence order is not wired into
  `test-stack-teardown.sh`, `buffer-recall.sh`, `pressure.sh`, or other
  production fixture cleanup. Existing normal removal and holder checks still
  fail closed, but they do not yet record this explicit kernel-drain evidence.
- The model verifies state transition logic only. Rootless positive model
  tests do not qualify a kernel DM driver, a block target, device cache
  durability, system swap, a loop device, or a real backing store.
