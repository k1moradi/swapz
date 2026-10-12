# V3.0.0-alpha.5: online packing + GC economics independent retest gate

**This file describes a TEST CANDIDATE, not a release.** All work must pass
the existing [LIVE_TEST_GATE.md](LIVE_TEST_GATE.md) and
[PRODUCTION_READINESS.md](../../PRODUCTION_READINESS.md) requirements.
Only an independently owned RAM-backed `null_blk` is permitted by the
kernel constructor. **Do not remove this guard. Never reboot. Do not modify
active swap, the protected SD partition or other device mappings.**

## Provenance and module identity

Pin exact PR source/head SHA and every production blob hash:
`dm-target.c`, `engine.c`, `authority.c`, `codec.c`, `gc-cost.h`
and `Makefile`. Separately record the built `dm-swapz.ko` digest,
vermagic, kernel version, loaded `dm_swapz` module and
**the actual target keyword `swapz3`**. V2.2 and V3 build the same
module BASENAME and must be tested one at a time, using isolated builds
and verified module teardown between them. The previous alpha.1
`dm-swapz3.ko` hash is NOT qualification of this kernel.

## New actual Device Mapper table arguments

```text
<owned_memory_backed_nullb_block_device> [read_cap 0..3] [window 1..64]
                                     [write_verify 0..1] [gc 0..1]
                                     [coalesce_ms 0..4]
```

All optional arguments are positional. Defaults:

- `read_cap=0`: optimizer minimizes bytes without a read-block cap.
- `window=64`: 64 compressed records maximum per bounded write batch.
- `write_verify=0`: optional whole-extent readback disabled; enable 1
  **only for corruption experiments**, separately account the extra reads.
- `gc=1`: choose victim by estimated LIVE **payload bytes** plus 16B
  metadata per compressed record; `gc=0` is the old LIVE **record-count**
  control. Neither is a claim about internal NAND or device sector size.
- `coalesce_ms=0`: immediate old worker behavior (control); choose
  `1,2,4` for opt-in bounded admission accumulation. On some kernels
  a 1ms delay rounds up to one jiffy; record actual `CONFIG_HZ`
  and observed admission/complete times, not the configured milliseconds
  as a guaranteed precise sleep duration.

The first accepted ordinary WRITE schedules the worker once. Following
writes can join before the timeout without prolonging it. **READ,
DISCARD, PREFLUSH, FUA and zero-length flush wake the worker immediately.**
The ordered worker still flushes pending writes before any barrier or
read, blocks duplicates from being staged together, caps each invocation
to 64 upper BIOs, and completes only after real lower I/O. Suspends
accelerate any timer and drain all accepted work.

## Required drain-race review after main-developer correction

The initial alpha.3 code compiled and passed rootless checks but used
`flush_delayed_work()` and `flush_workqueue()` for suspension while
the finite-window worker could **requeue itself**. Upstream workqueue
semantics do not justify treating a single delayed-work flush as a
complete flush of all later chained instances. The follow-up source
now closes BIO admission under `queue_lock`, forces the pending timer
to run, and calls `drain_workqueue()` after the delayed flush.
When admission is closed, the worker drains all earlier accepted BIOs
in the same invocation with periodic scheduler yields, instead of
requeuing an unbounded chain of 64-BIO work items.

**Independent host qualification is mandatory.** Run at least 1,024
accepted mixed compressed/raw writes (more than 16 worker quanta)
while concurrently suspending/resuming the owned test DM target.
Verify every upper BIO completes exactly once, byte-exact readback,
no delayed callback after teardown, and no `workqueue` / lockdep /
hung-task warning. Repeat with `coalesce_ms=0,1,2,4`, FUA barriers,
a pending timer at suspend, and lower I/O faults. Any hang or callback
ownership uncertainty is a STOP condition; do not force teardown.

## NEW hard release blocker: exact alpha.3 reclaim-progress reproduction

Independent Codex [PR #49 result](https://github.com/k1moradi/swapz/pull/49#issuecomment-6129397157)
found `-ENOSPC` after two successful GC relocations on **32MiB null_blk
backing, 1024 logical swap pages**, while moving compressed survivors
from fixed reserve segment30 to reserve segment31. The old selector
admitted reserve victims, and the foreground cursor was restored
outside the reserve tail after GC. There was **no demonstrated false
upper completion or data corruption**, but **progress FAILED**.

The main developer fixed this in [PR #50](https://github.com/k1moradi/swapz/pull/50)
and version **3.0.0-alpha.5**, with explicit per-1MiB-segment roles:
foreground only selects foreground victims, GC writes into ONE verified
dead reserve destination, and a completed all-live evacuation
**atomically swaps roles** so the old victim becomes a free reserve
segment and the new destination becomes foreground writable.
The foreground cursor remains inside the newly compacted segment,
not restored into the old exhausted foreground pool.

**The very first loaded test for alpha.4 MUST be a high-priority
reproduction gate, before faults or benchmarks:**

1. Pin the exact new `dm-swapz.ko` source blob SHA, module SHA256,
   vermagic and DM UUID. The old alpha.3 `a006d565...` module
   SHA256 is not evidence for alpha.4.
2. On a new **test-owned, memory-backed** 32MiB `null_blk` device,
   configure the same 1024-page logical target, GC byte policy and
   payload mixture that exposed the original problem. Test *no
   physical SD/SSD/HDD*, *no system swapon*, *no reboot*.
3. Force **at least EIGHT full live-record GC rotations**, not merely
   two. After each, assert `gc_role_rotations` increments,
   `last_gc_victim` refers to a previously foreground segment,
   `last_gc_destination` refers to its genuinely reserved GC
   destination, and the newly foreground destination has room for
   at least the expected next page. The reserve-role count must remain
   constant (two in this test) and no unverified segment may be reused.
4. Immediately submit a new foreground write after every successful
   GC. It must **not** fail because the reclaimed victim lies in
   the former fixed reserve tail. Byte-verify ALL 1024 relevant
   logical pages after each GC phase, including compressed and raw
   survivors plus zero/discard and same-slot overwrites.
5. Compare the `gc_policy=0` live-record count and `gc_policy=1`
   live-byte score with identical fixtures and show the selected
   victims. **GC selection from a reserve-role segment is a failure.**
   Record actual lower read/write bytes AND requests, GC overhead and
   attempted vs completed I/O. An estimate in
   `gc_selected_bytes` is not a measured physical-sector saving.
6. Inject a lower write failure midway through victim evacuation and
   a case in which survivor bytes cannot fit ONE reserve segment.
   No role exchange may occur; previous authoritative mappings
   remain valid, no foreground BIO can be falsely acknowledged,
   and the target must fail closed/quarantine uncertain media.
   Do not force-remove a target with unknown callbacks.
7. Only after this exact progress/integrity gate passes may you
   proceed to the coalescing, FUA, concurrency and sustained
   low-QD benchmark matrix below.

**Rootless evidence is not loaded-host proof.** The new exact C
tests `extent-v3-gc-rotation-test.c` (four-segment repeated
handoffs plus an eight-rotation 32MiB reproduction) and
`extent-v3-gc-engine-rotation-test.c` (byte-exact full compressed
engine readback plus injected failed relocation) exercise the real
authority/codec engine in memory, not the DM/kernel lifetime.

## Functional and concurrency safety before benchmarking

- Byte-exact independently verified compressed/raw roundtrips (including
  overwritten and discarded pages), pages sharing extents, generation
  transitions, finite reserve and victim GC, continuous mixed read/write
  plus repeated full-capacity verification.
- Explicit upper `REQ_FUA` and flush failure order; repeated urgent
  READ, DISCARD and PREFLUSH while a normal WRITE timer is pending.
  Confirm that each barrier forces earlier pending writes to publish
  before upper read, and upper completion occurs exactly once.
- Delayed timer + presuspend/resume/unload with queued writes; ensure
  no left-behind upper BIOs, no worker running on freed context and no
  new BIOs accepted after drain closes.
- Verify the new `payload_length` volatile authority field is exactly
  the actual on-media LZ4 length, raw pages report 4096, CRC/sequence
  is still checked, GC refuses malformed length or failed mapping.
- Run more than two full GC wraps, with two admissible candidate segments
  chosen differently by live-count vs live-byte score (e.g. one 3500B
  record versus three 500B records). Verify the destination never
  intersects a protected OPEN or in-progress victim segment.
- Controlled lower write/read/flush error injection: unchanged older
  mappings and no false successful upper BIO on a torn or failed write.
- Record kernel logs including lockdep, hung-task and workqueue CPU-hog
  warnings. One such warning **fails** the candidate until debugged.

## Paired online packing experiment (do not assume success)

For each `coalesce_ms=0,1,2,4`, same approved owned RAM null_blk
capacity and target layout, compare the **actual loaded kernel**
with identical exact-LZ4 payload seeds and arrival schedule:

1. Single-page QD1 stream with 50%-like 2082B compressed payloads;
   measure the added delay cost and possible inability to batch.
2. QD4 / QD8 / QD32 bursts with the same record sizes and target logical
   addresses; report **achieved** IOPS, not offered/target IOPS.
3. Clustered 8×large (~2224B) then 8×small (~1623B) batches versus
   alternating large/small, and repeated 50% / 75% record distributions.
4. Competing cold readers, repeated overwrite/discard and frequent
   FUA barriers. Measure read p50/p95/p99, CPU and recovery time.
5. During sustained churn, compare `gc=0` versus `gc=1` at otherwise
   identical settings and compressed-size histograms.

Before and after *fully drained* phases, reconcile lower device
`/sys/block/<owned_nullb>/stat` 512-byte accounting-sector deltas,
read/write request counts and driver `physical_read`,
`physical_write`, `gc_read`, `gc_write`, `gc_read_reqs`,
`gc_write_reqs`, submitted attempted counters and lower flush activity.
A 16KiB I/O is 16KiB transferred, perhaps **one request**, and **four
normalized 4KiB units**, NOT four actual physical operations.

Also record `window_records`, `one_page_windows`, `win1`,
`win2`, `win3_4`, `win5_8`, `win9_16`, `win17_64`,
`coalesce_deferred`, `coalesce_urgent`, actual LZ4 payload histogram
and `gc_selected_bytes`/`gc_selected_pages`. Confirm the histogram
sums to `windows` and the weighted window counts to `window_records`.

**Success is NOT simply a lower write-byte number.** It requires no
correctness regressions, measured lower **read AND write bytes and
requests** including GC, matched achieved rates, and acceptable cold
swap-in p99 / CPU / upper completion latency. A 4ms coalescing policy
that improves packing but makes QD1 swap-out unacceptably slow may be
inferior to the baseline; preserve this negative finding.

V2.2-vs-V3 control is required before physical media and before calling
the new design a production performance win. Do not infer SD endurance
from RAM-backed null_blk, modeled geometry or host sector totals.
