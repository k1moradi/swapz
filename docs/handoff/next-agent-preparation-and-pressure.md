# Agent handoff: preparation ordering and pressure qualification

## Summary

The round delivered a portable prepared-state acquire fix, not a demonstrated
performance gain. Source `3ef72d9f67d642e832e2f5420c283f6824969648` is committed
on main. Its owner report `fd5ed47e398e9c112f82e8c0b83dbbefd9f4aa2b` is BLOCKED.
Closeout commit `4c720de57ebe3e9f057c449a35c9eb12f826f4d2` records the result.
No test is still running. The broader useful-service goal remains incomplete.

Read [the detailed closeout](preparation-ready-acquire-result.md),
[the estimator qualification](prepared-cost-coverage-result.md), and governing
context, VISION, coding/testing standards and ROADMAP before changing code.

## Delivered behavior

The earlier owner-qualified estimator repair (`bb665730`, report `48a1580f`)
publishes each asynchronous page's LZ4 elapsed delta before READY; the ordered
consumer updates the EWMA only for READY_COMPRESSED/READY_RAW.

The latest fix in `src/kernel/preparation-slots.h` reacquires stable state when
the consumer loses PREPARING-to-RAW cmpxchg to producer READY publication.
Failed conditional RMW has no portable acquire guarantee. The consumer holds
its page reference, preventing reuse during the reread. Ordinary READY and
successful RAW claims retain one acquire read. No wait, retry loop, new worker,
reference, buffer, codec policy, format or lower-I/O depth was introduced.

The native test injects both READY representations between read and CAS, using
relaxed CAS failure ordering. Old-header and compiled relaxed-reread mutants
fail; fixed threaded reuse (8192 transfers) and ASan/UBSan pass. This is an
API-level regression, not LKMM proof or observed weak-memory corruption.

## Exact qualification boundary

Official make test completed in 2085.68 seconds, exit 2. Build, native/rootless,
W=1 and W=2 passed. Before ID36, loaded lifecycle/oracles, GC, TRIM, drain,
faults, handoff, RAW reads, mixed/storage regimes, coalescing and sustained QDs
passed. All 66 recorded WRITE arms retain required compression, positive EWMA
and drained prepared/submitter gauges. Overall loaded correctness is INCOMPLETE.

ID36's raw/uncompressed replay exceeded its 280-second timeout before swapz
replay. A read-only stack showed memory.high charging during filemap faults.
The fixture uses 576 MiB ballast and eight CPU workers. No limits were relaxed
and no replacement observation was collected. After preserving the timeout,
the agent created only that fixture's existing pressure.stop barrier because
active pressure was delaying cleanup too. Normal teardown finished; no DM
targets or pressure/replay workers remained. Do not describe this as unattended
cleanup acceptance or full owner qualification.

Local evidence is under build/optimization-round/preparation-ready-acquire/:
source-identity.json, full-test.log, qualification-state.json,
qualification-report.json, qualification-audit.json, pressure-pair-blocked.log,
pressure-cleanup-intervention.json, native/sanitizer/mutant logs. These ignored
artifacts stay local; the source, public report and durable handoff are in Git.

## Performance and next work

This BLOCKED run must not enter the PASS history. The generator refreshed five
plots but retains seven same-host PASS reports / 74 points, latest bb665730.
Read history JSON/CSV rather than decoding images. Fast persistent WRITE means:
QD1 raw/swapz 16.43/12.21 MB/s; QD4 73.01/35.92; QD8 85.16/61.65;
QD32 85.16/106.59. Raw-normalized changes versus the previous qualified report
are -1.4/-5.1/-4.8/-7.4%. These are watchpoints, not causal source A/B results.
Fast mixed swapz service is almost flat while raw controls rose. Do not promote
this correctness fix as a performance improvement. Low-QD and SATA/NVMe gaps
against raw remain open.

Investigate pressure startup and failure cleanup before another full run.
Preserve genuine memory/CPU pressure, source identity, raw controls, and existing
bounds; do not simply raise allowances, preload away the tested scope, retry
until green, or weaken acceptance. Separate any harness repair from a product
performance claim. Require exact-source owner qualification for retained C.

## Operating constraints

- Work directly on main; pull first, preserve concurrent report updates, no new
  branches/worktrees, force pushes or destructive resets.
- Use make fast_test for development; only make test qualifies/publishes.
- Keep delta64 + DELTA64_SHUF8 byte shuffle + LZ4 on in all emulated arms.
- Only positively owned RAM-backed null_blk. No physical storage, active swap,
  swapon/swapoff, reboot or forced mapper removal.
- Host is an old i3-M330, two physical/four logical CPUs, SSE2, about 4 GB RAM;
  tested kernel 7.0.0-38-generic. Do not assume idle/exclusive access persists
  without checking current user context.
- Do not restart a quiet live test. Preserve its handle and report stages/timing.
- Keep K=1, current pool and original submitter lifetime. Prior early-release,
  wake-suppression and larger-hand pilots were removed or unpromoted; consult
  ROADMAP IDs 165–173 before repeating them.
- Commit scoped verified changes and push main; verify matching remote ref.
  Do not mark the broad goal complete from this round's narrow repair.
