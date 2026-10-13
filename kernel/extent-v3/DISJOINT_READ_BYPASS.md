# V3 alpha.8: opt-in disjoint-read/write-window experiment

**Status: DRAFT / NOT LOADED-QUALIFIED. No physical media, active swap or reboot.**

## Motivation and independent observation

Codex PR #58 independently exercised PR #57 at
`2e71c0c90b7f6f4ec96340583a0bc5c517bae97c` on a *test-owned*
memory-backed null_blk. On the 80/20 mixed saturated 30-second QD8
workload, real backing write requests were **27,592 for frozen V2.2**
and **60,448 for alpha.7 / PR #57 bulk=1**. At QD32 the counts were
**7,353 and 41,003**. These are absolute saturated counts with
different achieved IOPS; a separate fixed-rate 1,500-IOPS comparison
also slightly favored V2.2 for lower bytes and requests.

The current V3 worker calls `sv3_flush_window()` before EVERY read,
including one accessing a separate logical region. The independent
benchmark uses disjoint writer pages 0..1023 and reader pages 2048..3071,
so most such flushes do not protect a same-page read-after-write
dependency. They prematurely close producer windows and increase the
number of actual lower WRITE requests. This is a testable source-level
bottleneck hypothesis, NOT a measured cause-and-effect claim.

## Candidate behavior

The optional **tenth** table argument is `read_bypass 0|1`,
default **0**. Alpha.8 intentionally preserves the old behavior unless
the user opts in on an owned null_blk instance.

When `read_bypass=1`, a valid ordinary one-page READ may bypass a
pending, unsubmitted write window **only if its logical page is absent
from every queued write**. Its read uses the already authoritative
mapping and does not publish any pending write early. A READ touching
any queued logical page MUST drain first. PREFLUSH, FUA, discard, all
other operations, and suspend still preserve the original full-drain
path. The worker remains single threaded and flushes any pending
window at every 64-BIO quantum boundary and before returning.

Since different logical pages are independent absent a requested
barrier, a plain read of page B may complete before a pending write to
page A becomes authoritative. Do NOT opt into this mode if ordering
across disjoint LBAs without an explicit block barrier is assumed by
the workload. Full correctness on swap-style workloads requires
independent loaded validation; this is not production approval.

If such a bypassed read produces a lower I/O/integrity error and
fails the target closed, the worker completes every previously owned,
still-unsubmitted upper write BIO with the latched error **without
attempting lower write publication**. No pending mapping is staged by
this error-drain branch. This is necessary because an unrelated read
can now fail while writes are buffered.

Status includes `read_bypass`, `read_bypassed` (ordinary reads
actually crossing a nonempty pending window) and
`read_conflict_flushes` (attempted bypasses that overlapped at least
one queued logical page). The standard window histograms, lower
submitted/completed, GC and flush counters are unchanged.
The DM table status round-trips the tenth argument. All existing
nine-argument or shorter V3 tables default to `read_bypass=0`.

## Loaded null_blk gates (not optional for performance claims)

1. **Exact provenance.** Same running-kernel W=1/W=2 builds and
   source-contract tests; record module SHA, Git SHA, target UUID,
   major:minor and all test fixture hashes. Never use a physical
   device, active swap, another mapping, or `swapoff`/`swapon`.
2. **Historical A/B:** original 1,024-page 819/205 burst with
   `read_bypass=0` must reproduce the PR #57 base counts, confirming
   no default-path change; compare `read_bypass=1` separately.
3. **Same logical slot RAW:** enqueue a write of A, then read A.
   The read must observe the newly written generation; predicate
   records a conflict, forces completion of the write window, and
   never returns the previous page. Test raw, compressed, and
   compressed-to-raw overwrites.
4. **Disjoint RAW:** enqueue a write of A and read B (different
   logical pages), with B prepopulated and byte-verified. Confirm the
   read can complete through the authoritative map without
   publishing/ACKing A prematurely. Use a controlled kernel BIO
   helper to observe completion ordering and status counters.
5. **Barriers and mutation:** PREFLUSH|WRITE, FUA writes, discard
   of overlapping and disjoint slots, duplicate writes, suspend,
   worker quantum rollover, and fail-closed error. Test exactly-once
   completions with bounded timeouts.
6. **Bypassed-read fault:** make the exact *test-owned* backing
   read fail or return a corrupt compressed/raw record while pending
   writes remain; verify pending writes all complete with EIO,
   no pending window runs after failure, and the target is safely
   removed after callbacks drain. No global block fault injection.
   Mark BLOCKED if no isolated deterministic mechanism exists.
7. **Sustained counterbalanced economics:** frozen V2.2, PR #57
   `read_bypass=0` and alpha.8 `read_bypass=1` with fixed
   `lower_bulk=1`, `coalesce_ms=0`; paired QD1,4,8,32 runs,
   10-second warmup and 30–60-second measurement, >=5 repeats
   for main workload. Repeat 80/20 disjoint and SAME-REGION mixed
   reads/writes, all raw, 1031B, 2088B, 3499B, and full GC churn.
   Compare **actual matched achieved** IOPS separately from
   saturation.
8. **Reporting:** backing `/sys/block/owned_nullb/stat` writes
   and reads in 512-byte sectors multiplied by 512; request counts
   separately; p50/p95/p99 read/write; kernel+user CPU and module
   memory; window size and bypass/conflict histograms; GC costs;
   and exact byte-verified pages. Do not compare raw saturated
   absolute totals at unequal achieved throughput as an equal-load
   cost metric. Do not infer NAND endurance from RAM null_blk.
9. **Unresolved PR #58 accounting:** every original sustained
   trial had exactly one more backing write request than
   `physical_write_reqs` with **identical write bytes**.
   Investigate zero-length WRITE/PREFLUSH and benchmark helper
   lifecycle using *owned-device-scoped* block trace; do not
   silently treat it as an extra 4KiB write or as settled.
   Five generic asynchronous page-read errors on dm-0 during
   synthetic GC faults also require attribution before fault-path
   release approval.

**Promotion criterion:** no integrity/ordering regressions, explicit
barrier safety, no pending post-failure writes, and a repeatable
statistically meaningful reduction in *actual* lower request count at
matched achieved load, without unacceptable read/CPU/p99/GC cost.
If the observed improvement is absent, keep this toggle disabled and
report the negative result. Avoid modifying the V2.2 control.
