# Experimental live-swap trial and recovery

**Status: owner-waived, one bounded trial authorized; not a production deployment.**
`LIVE_SWAP_EXECUTION_ENABLED` is true in the commit that carries this text. Each
`run` still needs a one-use approval record bound to that exact commit, to both
current CI workflows, to the qualified artifact hashes and to the live target.

The owner waived the separate external-review requirement for this one trial on
2026-11-02. That waiver is an owner decision. No external reviewer approval
exists in this repository or on issue #76. The adversarial review performed
before this change was run by internal agents; it is not an external review.

This procedure is separate from the completed physical-backed byte-correctness
smoke. It does not authorize repeated trials, boot integration, production use,
endurance measurement or performance claims.

## Trial boundary

- Only `/dev/sda4` (8:4, PARTUUID `7fb9401d-04`, UUID
  `728b4c06-44b0-46ee-91ec-560ab1bad358`) is touched. It is the PC's only swap
  area. No other disk, partition or swap entry is written.
- No fallback swap. The owner accepted that no independent swap exists while the
  trial runs. Before any mutation the plan requires the original partition to be
  the only active swap area.
- Logical capacity is the maximum admitted for the full partition: 3,355,136
  pages, 13,742,637,056 bytes (26,841,088 sectors). Linux sees 13,420,540 KiB
  usable. The SWZ header, 1 MiB segment alignment and the
  `ceil(logical_pages / 4)` GC reserve (838,784 physical blocks) account for the
  rest. The whole 16 GiB partition cannot be exposed as logical swap because
  about a quarter must remain reserved for GC.
- The trial lasts at most 30 minutes after the mapper becomes swap.
- RAM use (`MemTotal - MemAvailable`, over `MemTotal`) must be below 50 percent
  before the original swapoff. The swapoff itself requires `MemAvailable` to
  cover the bytes currently swapped on `/dev/sda4`, plus the 2 GiB reserve and
  a 1 GiB trial headroom. Admission, the baseline and every in-trial sample use
  that same 1 GiB headroom, so the plan cannot pass a host the trial would stop
  on. Cleanup keeps the approved 512 MiB drain margin.
- Conservative stops end the trial as `SAFE_STOP` with normal swap restored:
  memory pressure outside the bounded swap-pressure check (MemAvailable below
  2 GiB, PSI some at or above 5 percent or full at or above 1 percent, cgroup
  headroom below 512 MiB), drain headroom below 1 GiB, an operator stop, or RAM
  not low at admission.
- A failed swap-pressure check is `FAIL`. Normal swap is still restored.

## Swap-pressure check

After the baseline observation, the coordinator starts one child process inside
a new cgroup v2 directory with `memory.max` set to 128 MiB. The child fills a
320 MiB working set of 80,000 pages. Each page is 4 KiB, derived from the run ID
with SHAKE-256, and incompressible. It then reads every page back and compares
it byte for byte. The cgroup limit forces the kernel to swap pages out to the
swapz mapper and to swap them back in.

This host runs zswap with lz4 (`zswap.enabled=1`, 20 percent pool). Without a
bypass, the pressure could stay in the compressed RAM pool and never reach
`/dev/sda4`. The coordinator therefore sets the cgroup's `memory.zswap.max` to
0 and refuses to run if that control is missing. The pass also requires
`memory.swap.peak` above zero, and `memory.zswap.peak` zero when present.

The check passes only with zero mismatches, all 80,000 pages verified, exit
status 0, no OOM kill in `memory.events` and no timeout (15 minutes). An
operator stop kills the cgroup and ends the trial as `SAFE_STOP`. The PSI
thresholds do not stop the trial during this check, because the check causes
reclaim on purpose. MemAvailable (floor 2 GiB) and the 1 GiB drain headroom are
sampled every five seconds while the child runs; a breach kills the child and
ends the trial as `SAFE_STOP`. The child is forked from the supervisor that was
verified at admission, so it never re-reads files from disk. It joins its
cgroup, ignores terminal signals, arms a parent-death signal and its own
deadline, and reports through a pipe. The mapper's swap use is sampled during
the check, because the pages are released when the child exits.
The coordinator waits 60 seconds after the check before its next PSI-gated
sample.

A trial reports `PASS` only if, measured as deltas from the baseline, all of
these hold: kernel `pswpout` and `pswpin` both increased; dmsetup
`logical_write` and `logical_read` increased; the lower `/dev/sda4` write
counters increased; and mapper swap usage was above zero in at least one
sample. A trial with no swap traffic reports `ACTIVATION_ONLY`, which is not a
pass.

## Approval records

`run` accepts one JSON record. It must bind the run ID (32 lowercase hex),
the reviewed commit and CI commit equal to HEAD, both required workflows
`PASS`. The plan asks GitHub for those workflow results as the operator
(`gh run list`), so a record cannot claim a CI result that GitHub does not show.
The plan also pins the record's SHA-256 and the run refuses a changed record, the SHA-256 of the supervisor file and of the physical helper it
imports, the three artifact digests, the
device identity, the original header digest, capacity, duration, the pressure
parameters and `fallback_mode` `none`. It must use one of two modes:

- `verbal`: names the external reviewer `openai-chatgpt-external-reviewer` and
  carries the exact approval text. This needs an independent review record.
  None exists in this repository.
- `owner_waiver`: `reviewer` is null, `external_review` is `waived_by_owner`,
  and `external_review_waiver` is the exact waiver text in the code.

Both modes require the owner's authorization text. The waiver covers only the
external-review step for this one trial. It does not authorize later trials,
boot integration or production use.

## Durable state

All state lives under `/var/lib/swapz/physical-recovery/swapz-live-<run_id>/`
on the persistent recovery filesystem. Before swapoff the coordinator writes and
fsyncs the original 4096-byte header backup, the state, a bounded results
record and exact executable snapshots. It consumes the run ID permanently and
holds the partition lock and the active-recovery marker until restoration is
verified. The evidence contains no page contents.

## Normal shutdown

The coordinator stops observation, then checks drain headroom before the
swapoff of the exact mapper. Mutating tools run in their own session, so a
terminal Ctrl-C reaches only the supervisor. A stop request is honored at the
next step boundary, and a step in progress finishes. Zero-open checks on the
mapper, and the non-force remove, retry briefly, because udev probes can open a
fresh mapper. It never retries a failed mapper swapoff. If
swapoff fails, or pages remain active, it keeps the mapper, module, SWZ header
and recovery marker for supervised review. It does not force-remove a mapping,
unload a module that still has users, or overwrite an ambiguous header.

On successful cleanup the coordinator removes only its exact mapper without
force, unloads only a module it loaded itself with zero references, checks that
no backing holder remains, restores and rereads the exact original header, and
reactivates only `/dev/sda4` with its original size and priority `-1`.
Completion requires the absent helper mapper and module, a durable `COMPLETE`
state, the consumed-run record and a released marker. Post-restoration swap
usage is recorded for observation only. The mutation allowlist permits `swapon`
without a discard option and rejects discard requests. `mkswap` is permitted
only on the verified mapper and never with `--force`.

## Crash and cold-boot recovery

The mapping authority is volatile. If the machine crashes or reboots while swapz
is active, pages already swapped to it cannot be reconstructed from the saved
header backup. Those pages were held only by the mapper, so a crash can lose
them. This is the no-fallback risk the owner accepted. Nothing here claims data
recovery after loss of that mapping state.

After an unexpected stop, preserve the recovery directory. Do not reboot on
purpose, force-remove a mapper, reactivate `/dev/sda4`, or write block zero just
because a backup exists. First read the saved state, results and backup. Then
independently identify the live partition, mapper, UUID, exact table, lower
device, open references, module and active swap rows. If the mapper is still
active, or any identity or header is unexpected, leave it unchanged and escalate.
A live mapper may hold the only readable copy of swapped pages.

Before any cleanup step, the coordinator reconciles its persisted flags with the
kernel's tables. A mapper that is gone is recorded as gone. A live mapper whose
flag was never set is treated as live, so it is drained. The original swap is
treated as already off only when it is inactive, its stage was
`ORIGINAL_SWAPOFF_PENDING`, and no `swapoff` process is still running. Any
refusal is recorded as `REQUIRES_REVIEW` in the state and the results.

After a cold boot the former mapper and module are gone. `/dev/sda4` may still
hold a zeroed, SWZ-formatted or torn header. The fstab swap entry for that
partition is expected not to activate a header without a swap signature. That
expectation has not been tested on this machine. Normal boot does not restore the former swap
contents. The `recover` command accepts only a header it recognizes from the
saved state. It restores the exact saved 4096-byte header, rereads it and checks
ordinary swap size and priority. A torn header, a missing backup, a changed
partition identity or uncertain state stops for manual review. Rootless tests
model these decisions only. They do not prove recovery after power loss.
Physical cold-boot behavior remains unverified on this machine.

A rootless regression verifies that a saved `RECOVERY_REQUIRED` state is not
hidden when standalone cleanup records `TRIAL_STOPPING`. The recognized original
stage stays authoritative for checking the SWZ header. Missing or cyclic stage
provenance fails closed.

## Validation completed

Rootless tests (`tests/runtime/native/live-swap-supervisor-test.py`, 59 tests)
cover the capacity arithmetic against the kernel formula; drain and memory
gates; the approval modes and exact bindings; the plan gates, including the
no-fallback requirement; the exact mutation allowlist; mapper observation and
UUID substitution; swap-I/O evidence; the pressure child's byte pattern and
verification; pressure-workload orchestration with a mocked child and cgroup
root; full mock trials for PASS, SAFE_STOP, FAIL and REQUIRES_REVIEW paths;
interrupted activation; failed mkswap, swapon, swapoff and mapper removal;
ambiguous and torn headers; standalone recovery; reconciliation of persisted
flags with the kernel's swap and mapper tables (a vanished mapper, a live mapper
whose flag was never set, an orphaned swapoff); recorded REQUIRES_REVIEW for
recovery refusals; the CI query and its exact allowlist; the approval digest
pin; and the isolated-session mutation runner. These tests use mocks and
a temporary cgroup root. They do not exercise the kernel, real `swapon`, real
cgroup reclaim, a true cold boot or a physical trial.
