# swapz validation status

Date: 2026-10-07

## Version history

### V1

V1 is preserved on branch `v1` at:

```text
025edff9fbe1d402cf6eab294e3ce1627e49a1e9
```

V1 passed Linux 7.0.x correctness validation, but whole-live-set arena copying caused about
2.86x raw lower-device writes on partial/incompressible churn and approximately 1.03 second
rotation-triggering stalls on the 1 ms delayed test stack.

### V2

Validated V2 is preserved on branch `v2` at:

```text
1e3a0c71b4e514bccae58d79be9f319640478b5c
```

V2 replaced whole-live-set copying with 1 MiB segment-local GC. It reduced
partial/incompressible lower writes to approximately 1.00x raw and reduced measured
live-GC latency to single-digit milliseconds, but one synchronous 4 KiB lower request per
physical output remained a major request-overhead bottleneck.

### V2.1

The kernel/userspace candidate actually validated by Codex is preserved on branch `v2.1`
at:

```text
c841a589a44ada3561a8bbed83a4db86e530ee1c
```

The reusable runtime validation harnesses are merged into `main` under
`tests/runtime/`.

## V2.1 software-validation result

Final software/virtual status:

```text
CORRECTNESS PASS, VIRTUAL PERFORMANCE IMPROVED — PHYSICAL BENCHMARK NEEDED
```

Validation environment:

```text
Ubuntu 26.04.1
Linux 7.0.0-34-generic x86_64
4 KiB PAGE_SIZE
GCC 15.2.0
fio 3.41
```

The Linux 7.0 GCC `W=1` module build passed. Userspace and model builds passed, and the
model passed under ASan and UBSan.

The optional Clang kernel build was blocked by GCC-only options in that kernel's build
environment; this was treated as a kernel/toolchain-environment limitation rather than a
swapz source failure.

## V2.1 correctness coverage

The tested V2.1 commit passed:

- loop smoke, flush handling, and compressed I/O;
- raw and compressed segment-boundary regression;
- explicit physical-write-batching regression;
- five deterministic 100,000-operation randomized runs;
- long mixed live-GC churn;
- low-live victim selectivity;
- packed-container GC with 8, 4, 1, and 0 live records;
- lower DISCARD unavailable;
- lower read fault injection;
- lower multi-block write failure injection;
- 100 create/use/destroy lifecycle cycles;
- bounded real Linux swap pressure;
- swapoff and a second swapon/readback cycle.

The multi-block lower-write fault test submitted eight 4 KiB upper writes as one eight-block
lower request. The lower write failed, all eight upper writes failed, the target entered its
explicit failed state, and the prior successfully-written physical data remained intact.

No BUG, Oops, lockup, hung task, or panic was found during the completed validation suite.
Expected backing-I/O errors appeared during deliberate fault-injection tests.

## V2.1 write batching result

V2.1 coalesces up to eight consecutive 4 KiB physical output blocks into one serialized
lower write of up to 32 KiB.

The explicit batching regression wrote 256 raw pages / 1 MiB physical output using:

```text
66 lower writes
61 multi-block writes
maximum batch = 8 blocks
failed = 0
```

On the matched 1 ms/request virtual stack, fixed 64 MiB logical-write tests showed:

| Pattern | QD | V2 MiB/s | V2.1 MiB/s | V2.1 lower writes | Lower bytes |
|---|---:|---:|---:|---:|---:|
| 100% compressible | 1 | 1.908 | 3.663 | 16,384 | 64.00 MiB |
| 50% compressible | 1 | 1.905 | 3.665 | 16,384 | 64.00 MiB |
| incompressible | 1 | 3.678 | 3.672 | 16,384 | 64.00 MiB |
| 100% compressible | 8 | 12.638 | 20.942 | 2,095 | 8.29 MiB |
| 50% compressible | 8 | 3.446 | 20.533 | 2,056 | 64.00 MiB |
| incompressible | 8 | 3.675 | 20.692 | 2,077 | 64.00 MiB |

For QD8 50%-compressible traffic, V2.1 averaged about 7.969 physical blocks per lower
request, cut lower write-I/O count by about 87.45%, and improved throughput by about 5.96x
over V2.

For QD8 incompressible traffic, V2.1 averaged about 7.888 blocks per request, cut lower
write-I/O count by about 87.32%, and improved throughput by about 5.63x over V2.

For QD1 compressed/partial workloads, shortening the single-record pack wait from
500-1000 us to 50-100 us improved throughput from about 1.91 MiB/s to about 3.66 MiB/s,
close to the approximately 3.89 MiB/s raw baseline of this virtual test. Incompressible QD1
was effectively unchanged and already near raw.

Highly-compressible QD8 retained approximately 7.7x lower-byte reduction versus raw in this
run, although it wrote about 3.4% more bytes than the matched V2 run.

## V2.1 GC regression

The matched GC-latency run performed:

```text
8192 raw rewrites
31 GC victims
128 GC pages
64 KiB GC reads
64 KiB GC writes
```

Measured live-victim GC:

| Version | Average | Observed max |
|---|---:|---:|
| V2 | 3.842 ms | 4.883 ms |
| V2.1 | 3.858 ms | 4.320 ms |

No material GC latency or write-amplification regression was observed.

## Host-LBA and DISCARD findings

V2.1 retained V2's segment-local allocation/cleaning behavior. The validation suite
exercised lower DISCARD unavailable and live GC successfully. DISCARD remains optional for
correctness.

Host-write distribution is still only a host-LBA property. No claim is made about exact NAND
wear leveling because the device FTL remains opaque.

## Remaining gate

No physical HDD, USB flash, SD/eMMC, or SATA SSD was explicitly authorized for destructive
testing, so:

```text
PHYSICAL BENCHMARK: NOT RUN
```

V2.1 should now be treated as a software-validated proof-of-concept whose next engineering
gate is physical-device qualification.

Do not make another allocator or batching redesign before obtaining physical-device data
unless a new correctness defect is found.

The physical qualification must measure:

- QD1 and QD8 raw versus swapz throughput;
- 100%, 50%, and 0% compressibility;
- fixed equal logical I/O volumes;
- actual lower write-I/O count;
- actual lower sectors written/read;
- CPU use;
- latency distribution;
- GC bytes and GC-triggered latency;
- segment-cycle / host-LBA distribution;
- device DISCARD behavior;
- SMART or device health/write counters when genuinely available.

Primary target class:

```text
HDD / USB flash / SD/eMMC / old SATA SSD
roughly 10-100 MB/s
especially ~20 MB/s serialized devices
```

A strong physical success target remains approximately:

```text
incompressible QD1: >= 0.9x raw
representative compressible workload: >= 2x logical throughput where media bandwidth is the bottleneck
excellent compressible result: 3-4x logical throughput
highly compressible lower-write reduction: several-fold, potentially approaching the packing ceiling
total lower writes including GC: below raw for workloads where swapz claims an endurance benefit
```


## V2.2 current candidate

V2.1 remains the last software-validated baseline on branch `v2.1`.

`main` is now V2.2 / DKMS 0.2.2 and is intentionally **unvalidated** until the new
streaming/cancellation paths complete the Linux 7.0.x correctness and performance suite.

V2.2 adds three selectable policies:

```text
immediate
opportunistic
staged
```

and a configurable batch ceiling from 4 KiB through 1 MiB.

The important architectural differences from V2.1 are:

- asynchronous lower `dm-io` submission;
- exactly two preallocated stream buffers;
- one lower write may be in flight while the second buffer fills;
- no deliberate sleep merely to fill a batch;
- direct swap-in from either FILL or INFLIGHT RAM buffers;
- generation-based suppression of stale asynchronous completion;
- compressed staged foreground writes may complete before lower submission;
- logical DISCARD/overwrite can make an unsent staged record stale;
- the fill buffer is compacted/repacked before submission to avoid writing stale records;
- failed lower writes retain authoritative early-completed staged data for readback/swapoff;
- selectable batch size so the real throughput/latency plateau can be measured.

The current V2.2 implementation deliberately keeps the existing 4 KiB compressed-container
format while comparing streaming policies. A later byte-tight on-disk extent format must be
treated as a separate experimental variable; an incomplete intermediate conversion was
removed before this validation candidate was frozen.

### Request-size sizing result

The analytical 20 MiB/s command-latency model shows that there is no universal 128 KiB
sweet spot:

```text
0.25 ms fixed latency -> strict 97% point around 256 KiB
0.50 ms               -> around 512 KiB
1.00 ms               -> around 1 MiB
2.00 ms               -> strict 97% point above 1 MiB
```

At 2 ms, however, the modeled incremental gain from 1 MiB to 2 MiB is only about 2%, so the
measured latency-aware plateau may still prefer 1 MiB.

See `docs/benchmarks/v2.2-request-plateau-model.md`.

### Required buffer-recall regression

`tests/runtime/buffer-recall.sh` must prove:

1. a read from Buffer A while Buffer B is filling is served from staged RAM;
2. a read from Buffer B while Buffer A is being written is served from staged RAM;
3. reads from both buffers while one lower write is active are both served correctly;
4. a later logical invalidation of an unsent record allows repacking/cancellation;
5. read latency remains well below the deliberately delayed lower-device read latency.

A READ alone must not invalidate swap data.

### Required strategy/plateau benchmark

`tests/runtime/streaming-benchmark.sh` sweeps the three strategies and batch ceilings on a
controlled QD1 `null_blk` device while a concurrent reader generates swap-in pressure.

It records:

```text
upper write/completion throughput
end-to-end physical drain throughput
write avg/p99
read avg/p95/p99/max
lower read/write I/O counts and sectors
staged reads
staged early completions
staged cancellations
physical write requests
maximum write batch
CPU
```

For each strategy, the candidate sweet spot is the smallest batch at >=97% of the best
measured drain throughput, subject to a read-p99 latency guard.

The primary V2.2 decision is not simply which policy writes fastest. It is which policy
maximizes pages/reclaim completion while preserving acceptable swap-in latency and bounded
RAM usage.

No V2.2 physical-device claim should be made until this software suite passes.


## V2.2 blocker: asynchronous live-GC forward progress

The first Linux 7.0.x V2.2 validation attempt remains:

```text
BLOCKED — CORRECTNESS FAILURE
```

The checked-in staged-buffer recall fixture originally used 96 pages and could miss the
intended A/B timing window. Codex reduced that **test-only** fixture to nine pages while
retaining the assertions. The corrected fixture passed with approximately 15 ms recall
from each buffer and approximately 44 ms for the concurrent two-buffer read, including
staged cancellation. That test-only change is commit
`8b7c519f05e4d03cbb269c4080e6707866b843c1`.

The actual blocker occurred in the 3 MiB backing / 1 MiB logical live-GC correctness case.
A synchronous upper writer remained blocked in `submit_bio_wait` for more than 42 minutes.
The snapshot showed one upper BIO outstanding while no backing-loop I/O remained active.
Benchmarks and later correctness phases were correctly stopped.

Source review identified an unsafe progress dependency in the V2.2 asynchronous handoff:
the lower `dm-io` callback directly queued the same `io_work` item whose tail performs a
nonblocking reap. The candidate fix no longer relies on that same-work wakeup. A distinct
`completion_work` item is queued by lower completion; because the workqueue has
`max_active=1`, that kick remains ordered behind any currently executing `io_work` and
then queues `io_work` to reap/publish/complete upper BIOs.

Candidate fix:

```text
5596b8a01336c4d6853f83e90814540ccb98929d
```

Focused regression:

```text
tests/runtime/async-progress.sh
```

It reproduces the same 3 MiB / 1 MiB live-GC geometry with opportunistic 256 KiB streaming,
requires real live GC, and terminates after 120 seconds with target/table/lower-stat
diagnostics instead of hanging indefinitely.

This fix is **not yet validated**. Performance testing must remain stopped until the focused
progress regression and the broader correctness suite pass.


### Post-blocker candidate revision

After the blocked run, `main` also received a warning-cleanup change that moves the
fill-buffer compaction source snapshot out of the kernel stack and into preallocated target
context scratch, explicitly promotes the live-block status field for formatting, and marks
the Device Mapper status flag argument intentionally unused.

Current candidate:

```text
5f89799344aa1bd28bee535f706b60c4f07303bd
```

This cleanup is intended to be behavior-neutral, but because it touches the compaction
scratch implementation it is part of the next full Linux 7.0.x correctness rerun. No
performance result may be attributed to it before that rerun.


### Second async bug found during blocker re-audit

A deeper audit after the blocked run found a concrete stream-buffer lifetime race not fixed by
the first completion-kick change.

The old lower-I/O callback performed:

```text
write io_error
publish io_done = true
complete(completion)
```

while the nonblocking reaper treated `io_done=true` as permission to finalize, reset, and
reuse that stream buffer.

Therefore this interleaving was possible:

```text
lower callback                      io worker

io_error = ...
io_done = true
                                    observes io_done
                                    finalizes old buffer
                                    resets/reuses buffer
                                    reinit_completion()
complete(old buffer completion)
```

The final `complete()` could then act on a completion object already reinitialized for a
new lower request. Besides lacking a proper acquire/release synchronization edge for
`io_error`, this can cause premature completion of a later request or lost ownership of an
upper BIO.

Candidate fix:

```text
92753030d2783d7927816b5bcbce71592322fe30
```

The separate `io_done` flag has been removed. The completion object is now the sole lower
I/O completion state:

- blocking reap uses `wait_for_completion()`;
- nonblocking reap uses `try_wait_for_completion()`;
- the callback touches no stream-buffer state after `complete()`.

This ensures a buffer cannot be finalized/reinitialized until the callback has actually
published completion through the kernel completion primitive.

This race is a stronger candidate root cause for the live-GC hang than the earlier
same-workqueue wakeup theory. It is still not proven until the post-reboot focused regression
passes repeatedly.


## Pre-reboot V2.2 hardening pass

Before asking the operator to spend another reboot on runtime validation, `main` received
an additional source-audit hardening pass.

Concrete correctness fixes in this pass include:

1. **Late completion after unrelated failure must preserve the old mapping.**
   `swapz_install_mapping()` now checks `context->failed` before unaccounting the
   previously authoritative mapping.

2. **Same-slot staged replacement atomicity.**
   If the current generation of a logical page still exists in the compression pack or
   either stream buffer, a rewrite of that same logical page first drains the previous
   generation to disk before advancing the generation. This prevents an acknowledged
   RAM-only generation from becoming unreachable if its replacement later fails.

3. **Independent async watchdog.**
   Each in-flight stream buffer now has a delayed watchdog running on a separate
   reclaim-safe ordered workqueue. If the lower callback fails to arrive within the
   watchdog interval, the state worker fails outstanding non-early upper BIOs exactly once
   and freezes the target without recycling the lower-owned data buffer.

4. **Completion token consumed exactly once.**
   The blocking timeout path treats a successful `wait_for_completion_timeout()` as the
   consumed completion token and does not call `try_wait_for_completion()` again.

The same-slot failure regression is:

```text
tests/runtime/staged-rewrite-fault.sh
```

The source-only invariant gate was expanded so these properties can be checked while an
older module is still pinned and reboot permission is unavailable.

These changes remain runtime-unvalidated until a freshly built module is loaded after an
explicitly authorized reboot.


## V2.2 stale fill-buffer ownership root cause

The focused post-reboot run on
`3751bfb714c5aba77cdf987740b3bc60bcf6713e` reproduced the live-GC hang with a
much sharper ownership snapshot:

```text
writer: D / submit_bio_wait
failed=0
gc_victims=1
gc_pages=1
inflight_id=-1
inflight_blocks=0
async_cb=0
fill_blocks=0
pack_records=0
lower loop unchanged
```

This ruled out a simple lower-I/O completion wait: the upper BIO was no longer represented
by the compression pack, current fill buffer, in-flight buffer, or async callback state.

Source review found the concrete ownership bug in `swapz_stage_write_block()`:

1. it cached `buffer = swapz_fill_buffer(context)`;
2. it called `swapz_ensure_physical_block()`;
3. at a segment boundary that helper can drain stream buffers, advance the segment, and
   run GC, all of which may change `fill_buffer_id`;
4. after returning, the function continued staging into the stale cached buffer pointer.

If the old buffer had become FREE, the current upper BIO could be copied into that FREE
buffer and disappear from all state-machine ownership. That exactly matches the runtime
snapshot above.

Fix:

```text
120d752f690fb8cc3b2d1c94155c95f0cad2c545
```

`swapz_stage_write_block()` now reacquires `swapz_fill_buffer(context)` immediately after
`swapz_ensure_physical_block()` and asserts that the reacquired buffer is in FILL state
before staging any record.

Source regression:

```text
7bb3d5d9527c262d4dd0046b0ea6c0b5466bc192
```

The source-invariant test now requires the fill-buffer reacquisition to occur after the
physical-block ensure and before the physical block is staged.

The exact failing tree is preserved as branch:

```text
v2.2-stale-fill-blocked
3751bfb714c5aba77cdf987740b3bc60bcf6713e
```

This is a strong root-cause match but remains runtime-unvalidated until the freshly built
post-fix module passes the focused live-GC progress test.


## V2.2 stale-fill focused validation PASS

The stale fill-buffer ownership fix was runtime-tested on
`0f40f52956ff0b4ffc18549b916a54ce55847c02` with a freshly built and directly loaded
`dm-swapz.ko`. Module `srcversion` matched the build artifact.

The focused `tests/runtime/async-progress.sh` gate passed three independent runs:

```text
run 1: 6.835 s
run 2: 6.563 s
run 3: 6.596 s
```

Every run reported exact live-set readback, `failed=0`, `gc_victims=38`,
`gc_pages=38`, and fully drained stream ownership:

```text
inflight_id=-1
async_cb=0
fill_blocks=0
pack_records=0
```

This is strong runtime confirmation that reacquiring the fill buffer after
`swapz_ensure_physical_block()` fixed the previously reproduced lost-BIO/live-GC hang.

A run-3 kernel-log delta included:

```text
perf: interrupt took too long (...), lowering kernel.perf_event_max_sample_rate ...
```

This message came from the perf subsystem, not swapz/DM/block I/O, and the swapz test itself
completed correctly. It is recorded as unrelated host noise, not a correctness blocker.

Status now:

```text
FOCUSED ASYNC/LIVE-GC PASS — BROADER CORRECTNESS STILL REQUIRED
```

No performance conclusion should be drawn until the broader correctness suite passes.


## V2.2 full correctness PASS

The stale fill-buffer fix kernel source
`0f40f52956ff0b4ffc18549b916a54ce55847c02` has now passed the complete virtual
correctness campaign with the freshly built module identity verified.

Passed coverage includes:

- five 100,000-operation randomized seeds in opportunistic mode;
- 30,000-operation live-GC readback;
- selectivity and packed-GC checks;
- five 100,000-operation randomized seeds in staged mode;
- staged 30,000-operation live-GC readback;
- staged A/B buffer recall and cancellation;
- staged lower-write failure recovery;
- same-slot staged replacement preservation with an incompressible replacement payload;
- no-DISCARD live-GC;
- lower read-fault and batched write-fault propagation;
- 100 create/use/destroy lifecycle cycles;
- loop smoke and segment-rotation regressions;
- physical-write batching regression;
- bounded real swap pressure including swapoff, second swapon, and readback.

No swapz/Device Mapper WARN, BUG, Oops, hung task, lockup, or deadlock was observed.
Expected injected lower-I/O errors and unrelated perf sample-rate adjustment messages were
recorded but are not correctness failures.

The exact tested kernel baseline is preserved as:

```text
v2.2-correctness-pass
0f40f52956ff0b4ffc18549b916a54ce55847c02
```

Post-validation harness cleanup on `main` made two test-only improvements without changing
the kernel source:

1. `staged-rewrite-fault.sh` now uses a deterministic high-entropy replacement payload and
   asserts raw fallback, matching the synchronous-failure scenario the test intends to cover.
2. staged fault tests accept either a built-in Device Mapper `error` target or a loadable
   `dm-error` module.
3. `correctness.sh` now accepts `SWAPZ_LONG_STRATEGY=staged` for the long randomized/live-GC
   gates while keeping selectivity and packed-GC opportunistic.

Status:

```text
FULL CORRECTNESS PASS — PERFORMANCE GATE OPEN
```


## Final-version resume/hibernate milestone

Resume and hibernation are intentionally excluded from the current V2.x correctness and
performance gates, but they are **not permanently out of scope**.

Project intent is:

```text
V2.x:
  volatile compressed swap
  correctness
  streaming/performance
  physical-media qualification
  deployment/boot integration

final version:
  persistent hibernation/resume support
```

The final implementation must not reuse the current volatile RAM-only mapping model without
a dedicated persistence design. Hibernation requires the swap contents and all metadata
needed to decode and locate them to survive power loss/reboot and to be available early
enough in boot for resume.

Therefore the final-version milestone must include, at minimum:

- an explicitly versioned persistent on-disk metadata/data format suitable for resume;
- crash/power-loss-safe publication rules for hibernation state;
- boot-time discovery and activation, likely including initramfs/dracut integration;
- validation that resume never consumes ordinary volatile swap state by mistake;
- compatibility/version rejection behavior;
- end-to-end hibernate/resume tests across reboot;
- recovery/failure tests for incomplete or corrupted persistent state.

Until that final milestone begins, Codex and current V2.x development must treat
hibernate/resume as deferred and must not change the current volatile architecture merely
to approximate future resume support.


## V2.2 null_blk bandwidth-backend limitation

The first controlled V2.2 streaming sweep did **not** establish a swapz performance failure.

The run used Linux `null_blk` with:

```text
mbps=20
completion_nsec=500000
hw_queue_depth=1
```

and reached the staged 512 KiB case. The target then timed out with one 128-block lower
request still outstanding.

Source review of Linux `null_blk` explains the failure:

- the `mbps` throttle replenishes a byte budget 50 times per second;
- its per-tick budget is `(1 MiB / 50) * mbps`;
- at 20 MiB/s this is about 419,420 bytes (~409.6 KiB);
- if a single request is larger than the current budget, null_blk stops the hardware queue
  and returns `BLK_STS_DEV_RESOURCE`;
- the next tick restores the same ~409.6 KiB budget;
- therefore a 512 KiB request can never become admissible and is requeued indefinitely.

The observed 30-second swapz watchdog therefore detected a synthetic lower-device livelock
caused by the benchmark backend. It must not be used as evidence that swapz cannot issue or
complete 512 KiB writes on a real device.

The checked-in benchmark now:

1. discovers configfs null_blk device/sysfs names portably;
2. computes the null_blk per-tick byte budget;
3. rejects unsafe batch ceilings before creating a workload that can wedge the host;
4. allows `SWAPZ_BENCH_MBPS=0` for latency-only large-request testing, clearly labeled as
   unthrottled.

At 20 MiB/s, null_blk-mbps measurements are therefore limited to batch ceilings no larger
than the backend budget. The standard powers-of-two sweep is safely measurable only through
256 KiB.

Status:

```text
CORRECTNESS PASS — PERFORMANCE BACKEND LIMIT, NOT SWAPZ PERFORMANCE FAIL
```

A size-aware synthetic backend or explicitly authorized physical media is required to
measure the 512 KiB / 1 MiB plateau at an actual ~20 MiB/s transfer rate without null_blk's
token-bucket artifact.


## V2.2 synthetic latency matrix: teardown failure

Linux 7.0.0-34 performance validation on
`9b0a0a2d193f19b7159983a2a47279c4f57ea597` again passed source invariants,
GCC W=1, userspace/model/ASan/UBSan, staged fault recovery, and staged
randomized/live-GC correctness (five 100,000-operation seeds; 30,000 live-GC
operations; 116 victims/pages).

The revised `null_blk` guard correctly rejected 512 KiB at 20 MiB/s. The following
synthetic benchmark workloads produced usable results:

- 20 MiB/s / 0.5 ms / <=256 KiB: full sweep passed; opportunistic and staged
  peaked near 16 KiB (16.57 and 16.76 MiB/s), dropping toward 11 MiB/s at
  256 KiB due to quantized null_blk bandwidth throttling.
- Unthrottled / 0.5 ms / <=1024 KiB: request-overhead/latency characterization
  passed; opportunistic peaked near 128 KiB (89.33 MiB/s), staged near 256 KiB
  (150.65 MiB/s). These are **not** 20 MiB/s physical-drain measurements.
- 20 MiB/s / 0.25 ms / <=256 KiB: completed.

The remaining 1 and 2 ms matrix encountered `dmsetup remove` returning
`Device or resource busy` after completed cases. The previous script's EXIT
trap ignored that failed removal, then powered off/rmdir'ed the test null_blk.
With the DM target still depending on a missing backing device, a subsequent
`-EIO`/Buffer I/O error was caused by unsafe benchmark teardown rather than a
demonstrated swapz data-path failure.

Post-report review fixed this test-only failure:

- `streaming-benchmark.sh` now requires successful and verified DM removal
  before publishing a case and proceeding to another;
- normal removal uses `dmsetup remove --retry` for transient opens, with no
  `--force` or `--deferred`;
- EXIT cleanup **preserves** the powered-on null_blk and diagnostic artifacts
  if the test DM target cannot be removed safely;
- the safety contract is isolated in `streaming-benchmark-teardown.sh`;
- `streaming-teardown-regression.sh` tests busy and false-positive removal
  conditions without loading kernel modules.

No kernel performance policy was changed. The host's final Codex snapshot had
no test DM/null_blk state or D-state tasks; the freshly built module remained
loaded and matched source.

Status: `CORRECTNESS PASS — PARTIAL SYNTHETIC PERFORMANCE, TEARDOWN RETEST REQUIRED`.

The next gate is the teardown regression and focused 1/2 ms reruns on virtual
devices; the physical bandwidth plateau remains unresolved.


## V2.2 GC churn blocked at lower DISCARD on throttled null_blk

Codex validated the safe benchmark teardown and then completed 100 synthetic cases:
1 and 2 ms batch matrices, QD and compressibility sweeps. All completed
cases had `failed=0`. The 1 ms guarded candidate was 32 KiB, the 2 ms
candidate 64 KiB, but the virtual results do not select a final physical-media
batch.

A subsequent 60-second configured GC-churn test ran for over 11 minutes and
did not finish. It used 20 MiB/s bandwidth-limited, memory-backed
`null_blk`, 0.5 ms latency, QD64, 50% compressibility, opportunistic 16 KiB.

Snapshot:

```text
failed=0
current segment 255/256
free_segments=0
gc_victims=1
gc_scanned=8192
gc_pages=0
inflight_id=-1
inflight_blocks=0
fill_blocks=0
pack_records=0
async_cb=0
one lower null_blk request remained in flight
```

Source review identifies a strong backend-specific explanation: GC increments
`gc_victims` before visiting the victim's live blocks. Even if the victim has
zero live pages, `swapz_clean_segment()` calls `swapz_try_discard_segment()`
before marking it free. For a fully written 1 MiB victim that function issues
`blkdev_issue_discard()` for **1 MiB synchronously**, blocking the sole swapz
worker. When null_blk has `mbps=20`, its per-50-Hz-tick limit is only about
409.6 KiB and its throttle accounts request bytes for DISCARD as well as
data operations; this can permanently requeue the 1 MiB discard.

The previous benchmark's request-size safeguard covered stream writes but
erroneously enabled lower DISCARD. The repaired bandwidth-limited fixture now:

- defaults `SWAPZ_BENCH_DISCARD=0`;
- refuses DISCARD-enabled `null_blk mbps>0` before device setup;
- configures the null_blk DISCARD capability to off;
- verifies every target reports `lower_discard=off` before its workload;
- preserves the existing <= per-tick write-batch limit;
- offers optional lower-DISCARD testing only with an **unthrottled** null_blk
  backend (`SWAPZ_BENCH_MBPS=0 SWAPZ_BENCH_DISCARD=1`) or separate correctness
  tests.

This is a high-confidence source-based diagnosis, **not yet a runtime-proven
resolution**. The current 11-minute stalled host state was left pinned,
with the lower null_blk powered on by guarded cleanup. Reboot requires the
operator's explicit authorization and cannot be inferred from this report.

Status:

```text
CORRECTNESS PASS ON PRIOR GATES — GC CHURN BLOCKED,
SUSPECTED OVERSIZED SYNTHETIC DISCARD, FOCUSED RETEST REQUIRED
```

After an operator-authorized reboot (if the pinned state cannot be cleared by
safe ordinary means), load the fresh matching module and run a focused extended
GC-churn test with lower DISCARD definitively off. Require genuine segment reuse,
`gc_victims > 1`, no outstanding I/O, exact readback when applicable, and no
hang/WARN/Oops before any remaining performance phase. Then run a separate
unthrottled discard-enabled live-GC check to retain optional-discard coverage.
Do not change kernel GC policy merely to compensate for this synthetic throttle
unless the focused test reveals a real kernel bug.


## V2.2 null_blk GC/DISCARD focused retest: PASS

Codex tested `main` at
`111fc89e4b7edb97f2f61c7e5fd5b3acd01ee137` on
Linux 7.0.0-34-generic with a freshly built W=1 module:

```text
built/loaded srcversion: C0E91E94E24D50FDC42769E
module SHA-256: 7a27b2cf2313ece3305d2dfed142bb2abb1c16ab72464da698633ef68068e41f
```

The source invariants, null_blk DISCARD guard, teardown mock regression, and
unsafe-config rejection all passed. `SWAPZ_BENCH_MBPS=20` plus
`SWAPZ_BENCH_DISCARD=1` returned exit code 4 **before** creating a test
device.

The two bounded 60-second GC churn comparisons used QD64,
50% compressibility, opportunistic 16 KiB batches, and 0.5 ms nominal
null_blk completion latency:

| Lower backend | GC victims | Lower DISCARD | Result |
|---|---:|---|---|
| 20 MiB/s null_blk, DISCARD off | 921 | `lower_discard=off` | `failed=0`, drained, safe teardown |
| Unthrottled null_blk, DISCARD on | 1,125 | `discard_bytes=1,179,648,000`; `discard_failures=0` | `failed=0`, drained, safe teardown |

Both runs completed with no outstanding lower stream request or callback.
Post-run inspection found no disposable DM targets, null_blk devices,
swapz loops, fio processes, or new related kernel WARN/Oops/hung-task messages.
The unrelated `/swapfile` and `/dev/sdb1` remained configured and were not
targeted by validation commands.

This is strong **runtime confirmation** of the earlier diagnosis: the
bandwidth-throttled null_blk backend can wedge on a whole-segment GC DISCARD
larger than its replenished byte budget. Disabling its lower DISCARD removed
the previously observed stall, and separately allowing DISCARD on an unthrottled
backend reclaimed over 1 GiB without error. No swapz kernel policy change was
needed.

**Scope of this PASS:** GC forward progress, optional lower-DISCARD behavior,
and safe teardown. The fio reader job does **not** provide byte-for-byte
live-set integrity verification. Prior randomized/live-GC correctness passes
remain valid, but this focused long-churn workload is **not** a new exact-data
integrity result.

Current status:

```text
FOCUSED GC/DISCARD PROGRESS PASS — V2.2 FULL PERFORMANCE GATE STILL OPEN
```

Next: on the confirmed clean host, run separate exact-readback live-GC
correctness coverage under appropriate bounded test conditions, then finish
cancellation, GC-read/write latency/amplification, bounded real swap pressure,
and performance comparison. Do not select a physical-media batch ceiling using
the 50 Hz null_blk throttle; 512 KiB/1 MiB at ~20 MiB/s require a size-aware
synthetic backend or an explicitly authorized disposable physical device.


## 2026-10-08: exact live-GC / pressure evidence and teardown-source hardening

Codex reported the following host campaign on `main` at
`d35455ec146ffed7aaed08a001764cd0e05324dd`, loaded/built
`srcversion=C0E91E94E24D50FDC42769E` (reported kernel logs and local
artifacts were not independently rerun in this primary-developer session):

- Opportunistic and staged each passed five 100,000-operation exact-reference
  randomized seeds. The long live-GC case passed 30,000 operations and 117
  checkpoints per strategy, with **116 actual relocated pages** each and
  `gc_read=gc_write=475136` bytes; `failed=0`. Opportunistic with lower
  DISCARD disabled also passed exact live-GC readback with 116 relocations.
- Staged canceled 10,446 unsent 4 KiB blocks across the matched five-seed
  randomized runs, avoiding 42,786,816 physical bytes against opportunistic;
  lower write-request counts also reflected 37 coalesced requests.
- Both opportunistic and staged completed two bounded Linux swap-pressure
  holds at an experimental matched 16 KiB batch, swapoff, second swapon, and
  exact readback. The first holds relocated 66,220 and 67,831 pages,
  respectively; both ended `failed=0`.
- The host report ended with matched loaded/built module identity, no
  test-owned mapper/loop/null_blk remaining, and the normal host
  `/swapfile` and `/dev/sdb1` swap entries unchanged.
- **Missing evidence:** no GC-trigger latency distribution and no swap-in
  p95/p99/max specifically during live-victim GC. Existing synthetic
  null_blk 20 MiB/s plateaus are backend-limited; the 512 KiB–1 MiB physical
  batch decision remains unresolved.

The same campaign showed that `no-discard-livegc.sh` and
`buffer-recall.sh` could report successful workloads while retaining their
test DM/loop dependencies. The primary developer subsequently committed
fail-closed, verified upper-to-lower teardown in those two scripts and
`pressure.sh`, plus `tests/runtime/test-stack-teardown.sh` and a mock
regression. Cleanup failure now prevents PASS, returns nonzero, and retains
diagnostics/backing. **This is source-only hardening, not yet a Linux-host
runtime validation of the changed scripts.**

Development-environment source-only checks passed for the corresponding
teardown helper and its busy/false-positive/partial/holder/writer mock cases.
The offline live-GC correlation analyzer and five rootless unit tests also
passed locally. Neither set of tests loaded the module or attached DM/loop/NBD.
See `docs/benchmarks/v2.2-live-gc-latency.md` for the proposed timestamps,
per-event relocation evidence, sample-size gate and clock-domain constraints.
Kernel `dm-swapz.c` is unchanged.

Next gates remain: independent Codex source-only review of this new teardown
code; separately authorized bounded virtual teardown/runtimes; source-only NBD
preflight and later NBD calibration; then exact live-GC tail-latency evidence.

## 2026-10-08 — Codex teardown audit follow-up (source changes, new gate pending)

Codex independently executed eight source-only checks at
`4307f0c9a3becb9c9e87a73f8609a3656c4ccf23`:
five Bash syntax checks, the rootless teardown mock, six GC-latency analyzer
unit tests, and Python compilation. All eight exited 0. The host's normal
`/swapfile` and `/dev/sdb1` swap remained unchanged and both pre-existing
untracked state files were preserved. This is host-reported evidence for the
**older** teardown source, not qualification of changes made afterward.

The audit identified fail-open inspection paths: cgroup.procs reporting zero
st_size while listing live PIDs; a failed losetup/awk inspection interpreted
as confirmed absence; suppressed systemd/readlink/proc-swaps errors; untracked
parallel recall readers; and ps errors enabling blocking wait. It also noted
missing analyzer invalid-input and tail-percentile regressions.

The primary developer implemented source-only fixes after that audit:

- `tests/runtime/test-stack-teardown.sh`: independently checked DM parsing;
  successful, exact-name loop inventory before/after detach; fail-closed
  unexpected inventory entries and holder-inspection errors; safe child
  ownership/state checks; and all-child quiescence.
- `tests/runtime/pressure-teardown.sh` (sourced by `pressure.sh`):
  read and validate cgroup.procs contents rather than its size; fail on
  unknown systemd state and swap/mapper inspection; confirm test swap
  inactivity independently of the SWAPON tracking flag before teardown.
- `tests/runtime/buffer-recall.sh`: track, stop, and reap both parallel
  readers as well as the writer before removing DM targets.
- Rootless failure-injection expansions for loop post-detach/inventory,
  DM parser, process inspection, cgroup, systemd, proc-swaps, swapoff and
  active swap; four new offline analyzer invalid-input/statistics tests.

**Current status:** changes are committed for independent Linux-host
source-only requalification; new/changed rootless regressions have not yet
been executed on the Codex host. No live kernel DM/loop teardown, NBD
attachment, GC-overlap swap-in p99, or physical-media benchmark was run
in this development step. Passing old checks does not authorize runtime
testing of the new cleanup paths.

Source-only follow-up (no device or root operations):

```bash
bash -n tests/runtime/test-stack-teardown.sh
bash -n tests/runtime/test-stack-teardown-regression.sh
bash -n tests/runtime/pressure-teardown.sh
bash -n tests/runtime/pressure-teardown-regression.sh
bash -n tests/runtime/no-discard-livegc.sh
bash -n tests/runtime/buffer-recall.sh
bash -n tests/runtime/pressure.sh
bash tests/runtime/test-stack-teardown-regression.sh
bash tests/runtime/pressure-teardown-regression.sh
python3 tests/runtime/live-gc-latency-analyze-test.py -v
```

## 2026-10-08: Additional size-aware NBD source safety review

Codex independently reported seven of seven NBD rootless commands PASS at
`0c3a9169b8efcab06ef8c2641d36885976a8ccde` with NBD Python
source blob `ad9637ade1895bd1f31a4fe9780530417f8f6597`.
The intentionally injected NBD slow-worker error and DM busy-removal
errors were present, and their preservation assertions passed.
Codex confirmed that the tested kernel blob
`7589022ecdf0525716717270ab063a867a21f473` matches the previously
validated candidate. No live kernel NBD, mapping, swap, or module operation
was performed.

The source audit identified incomplete coverage of missing/denied NBD
holders, illegal commands/flags, complete-client short READ payloads,
mid-request stop, maximum request boundary, partial NBD setup and failed
worker startup. It also found a shutdown diagnostic weakness: a failed
NBD_DISCONNECT could remain buffered if the kernel worker never exits,
and later descriptor-close exceptions could hide earlier failures.

The primary developer subsequently committed source-only corrections to
`tests/runtime/size-aware-nbd.py`: checked holders/PID/swap inspection;
immediate printing of disconnect errors; independent socket/fd close error
recording; expanded actual protocol-loop negative tests; modeled request
boundary and cancellation-during-wait tests; and mock `serve_kernel`
setup, startup, and final exit-status tests. No kernel source or concurrent
teardown test source was changed by this NBD follow-up.

**Evidence boundary:** These newer additions have NOT yet received the
same checked-out-HEAD Linux-host source-only execution. Neither rootless
selftest checks nor this report establish an actual NBD kernel smoke,
calibrated 20 MiB/s lower rate, GC-trigger latency, overlapping-live-GC
swap-in p99, or a physical batch-size choice. The next NBD gate is the
exact source-only command sequence recorded in `CODEX_VALIDATION.md`
after the concurrently assigned teardown audit is complete.

## 2026-10-08 — Follow-up P0 teardown fixes and executed rootless CI PASS

Codex independently audited teardown source at
`ae594c266d11a815091b5957b496b1705252db72`: seven Bash syntax checks
PASS, pressure teardown mock PASS, and ten offline analyzer tests PASS.
The DM/loop regression **FAILED** at an incorrect expectation after the
upper mapping had already been removed. Codex additionally reproduced two
P0 fail-open inspections: a successful but malformed `dmsetup ls` listing
was accepted as absence, and failed cgroup `-d`/`-e` inspections could
masquerade as a removed cgroup.

The primary developer committed fixes: validate complete `dmsetup ls`
NAME (major:minor) rows and reject bad parsing; inspect cgroup directories
using Python `os.stat` to distinguish ENOENT, present directory, and all
other errors; verify `cgroup.procs` contents when present; correct test
expectations for already-removed upper mappings; restrict child signals
to running or stopped shell jobs, not completed-but-listed PIDs; and
strengthen ordered pressure teardown mocks, unknown loop inventory columns,
systemd/mapper/swap inspection errors, and a missing foreground-read
result column.

A **rootless-only GitHub Actions workflow** was added at
`.github/workflows/rootless-teardown.yml`. Its successful run:

- **Tested commit:** `e92ad29a192b70cbe9e04a1421496bfaf85bd460`
- **Run:** https://github.com/k1moradi/swapz/actions/runs/37772741880
- Bash syntax (seven fixtures/helpers): **PASS**
- Full DM/loop teardown rootless regression (all mock cases including
  false-positive detach, malformed listing, find failure, live ps error,
  completed/recycled PID and three-child cleanup): **PASS**
- Pressure teardown rootless regression (cgroup tri-state including
  direct `os.stat`, systemd, swapoff, alternate active path, ordering):
  **PASS**
- Offline GC analyzer unit tests: **11 passed, OK**

The temporary preceding CI runs failed and were used to correct two
additional test-harness defects: a duplicate malformed shell fragment
and a missing restoration of the real loop-holder helper. The successful
run is the authoritative execution result; earlier failed runs are not
counted as PASS.

**Qualification boundary:** This verifies source-only behavior on a clean
GitHub-hosted Ubuntu runner. Codex's independent Linux-host rerun at the
new teardown SHA is still desirable. Even this PASS does **not** authorize
root-only fixture teardown, live NBD attachment, kernel module changes,
swap activation, physical disk operations, or reboot. The shell job
ownership check reduces stale PID signaling but cannot eliminate every
PID-reuse race between observation and signal without an atomic pidfd-
based signal. Never claim that all possible races are eliminated.

Kernel blob `7589022ecdf0525716717270ab063a867a21f473`
remains unchanged; current NBD source is handled by its own independent
source-only audit.

## 2026-10-08 — Rootless NBD requalification at a corrected mock-isolation commit

Codex previously tested NBD source blob
`bae63c5db31a621c2f25855a7a7c0dee5c7e7f78` at commit
`2fc80f4ead9da0fde5a725487e3744acff1fca28`. Its seven-command
source-only gate **FAILED** because the Python selftest did not reach
its final assertions. More seriously, the selftest patched `fcntl.ioctl`
and `os.close` but `shutdown_kernel_session()` had captured the original
syscalls as keyword defaults. The mocked cleanup consequently attempted
real NBD_CLEAR_SOCK and close against numeric fd 81. There is no basis
for asserting those attempted operations had no effect merely because
the host lacked sysfs NBD devices or showed no swap-entry change.

The primary developer fixed this by resolving the syscall dependencies
at shutdown invocation and replacing the mocked numeric fd with a
non-integer sentinel object, so a missed patch cannot issue operations
against a real descriptor number. The setup mock asserts ioctl and
close interception. The backend additionally records unexpected
non-OSError NBD_DO_IT exceptions as errors. Rootless regressions now
cover the previously skipped setup cases, an unexpected worker failure,
active NBD PID, unreadable swap information and selected-device swap,
and a complete 8 MiB socketpair READ/WRITE at the accepted request
ceiling. No real block/NBD device was opened by those tests.

**Executed evidence:** The GitHub Actions
`Rootless NBD source safety` workflow completed successfully on
`f1c458f638712a19dea8b724a7f32bd1052b791e`
at https://github.com/k1moradi/swapz/actions/runs/37774348723.
The workflow's source AST check verified non-captured `ioctl`/`close_fd`
defaults and presence of the fake-fd sentinel before running the selftest.
Python compilation, NBD selftest, three Bash syntax checks, NBD teardown
mock, and streaming teardown mock all **PASSED**.

This is a valid *rootless, clean GitHub-runner source-only PASS* for the
tested code, but Codex independent Linux-host requalification remains
pending. It provides no proof of live NBD driver behavior, actual
DM/loop teardown, GC-overlapping swap-in latency, physical performance,
or an authorized runtime experiment. The kernel remains unchanged.

## 2026-10-08 — Additional NBD source-only inventory inspection gate

The primary developer audited NBD preflight after the mocked syscall
isolation fix. `/proc/swaps` previously accepted empty output or
malformed-but-readable rows as if there were no active swap entries;
`/proc/self/mountinfo` similarly accepted empty output as an empty
mount list. This is a fail-open preflight interpretation even if the
corresponding proc read itself succeeds.

Updated `tests/runtime/size-aware-nbd.py` rejects empty/malformed
mount and swap inventories before NBD attachment and validates
swap-entry field types. A rootless positive preflight test also
confirms an unused virtual device with valid mount and swap inventory
(including negative swap priority) remains acceptable.

**Executed evidence:** Rootless NBD CI
https://github.com/k1moradi/swapz/actions/runs/37775709673
at `0b93caf752aa4716100815734d3a1f299fc2dec8`
concluded **SUCCESS**. The static syscall isolation guard, Python
compilation, NBD selftest, three Bash syntax checks, and NBD/streaming
teardown mocks all passed. An intermediate run failed because the
prior test fixture used empty mountinfo; the mocks were corrected and
the final source-only suite ran to completion.

This does not establish kernel-backed NBD runtime safety or physical
latency/cost measurements. The kernel and Codex-owned teardown
sources are untouched; host device operations remain unauthorized.

## 2026-10-08 — Teardown follow-up hardening after independent Codex PASS

Codex independently reported **SOURCE-ONLY TEARDOWN GATE PASS** at
`10c9d09bf4d3e78dd9524e20988c38b204f9ad42`: seven Bash syntax
checks passed, both rootless teardown regressions passed and the
offline live-GC analyzer passed all 11 tests. Its audit identified
defense-in-depth gaps (duplicate/out-of-range DM tuples, prefix-only
swap-inventory header, per-unit cgroup mock conflation, missing stopped
job test, and an insufficient active-stop-failure assertion).

The primary developer subsequently committed teardown-only corrections:

- `swapz_test_confirm_dm_absent` rejects duplicate DM inventory names
  and major/minor tuples outside the Linux 12-bit-major/20-bit-minor
  `dev_t` representation (up to 4095:1048575).
- `swapz_pressure_confirm_swap_inactive` requires an exact
  five-column /proc/swaps header and exactly five fields in each row;
  validates swap type, absolute path and numeric size/used/priority;
  rejects malformed output before mapper cleanup. Valid unrelated
  swaps with negative priority remain acceptable.
- Rootless regressions separately inspect the first and second
  test-unit cgroups, prove that failed systemd stop with active swap
  triggers **zero** swapoff/DM calls, verify unexpected inventory
  contents are rejected, and exercise a stopped-owned child through
  ordered CONT then TERM signals using mocks.
- The cgroup.procs regression explicitly describes mocked content
  behavior instead of claiming to construct a real pseudo-file.

**Executed evidence:** The GitHub Actions `Rootless teardown safety`
run at `68360c26214c4c08a57180f50ae032746d68342f` was **SUCCESS**:
https://github.com/k1moradi/swapz/actions/runs/37777532521.
All seven Bash syntax checks, the complete DM/loop and pressure rootless
regressions, and 11 offline analyzer tests passed. Earlier intermediate
CI failures were test-fixture syntax/duplicate-source defects; they
were corrected before the successful run.

**Remaining child-identity limitation:** The existing jobs -pr/-ps
checks reject completed-but-listed PID reuse and the new test covers
stopped children. There is still a TOCTOU window between job-state
inspection and `kill -CONT`/`kill -TERM`. A process start-time
comparison would not eliminate that window; atomic pidfd-based signal
delivery would require a separately reviewed implementation and
fixtures. No new real process-signaling mechanism was introduced.

This is rootless source-only validation, not authorization for real
NBD, DM/loop, swap, kernel module, fio, physical media or reboot.
Kernel blob `7589022ecdf0525716717270ab063a867a21f473` is unchanged.
The concurrent NBD independent audit remains a separate qualification.

## 2026-10-08 — Codex NBD source-only FAIL corrected; 26 rootless PASSes

Codex independently tested NBD source blob
`9abcce54fb2cb892e64132ad2b76244110383092` at
`977023f4aca61e4e8d408065504966f3646b5eee`.
Its syscall-isolation review **PASSED**. Six of the seven source-only
commands **PASSED**, but `size-aware-nbd.py selftest` exited 1 with
`AssertionError: [OSError(9, 'Bad file descriptor')]`: in the 8 MiB
socketpair case, the test closed its sockets before joining its
still-active server thread. The resulting EBADF prevented the later
mocked NBD_SET_SOCK cleanup/worker-start cases from executing in that
host run. The error came from userspace test cleanup, not from a real
NBD ioctl.

The primary developer reordered cleanup: set the stop event, join with
a finite deadline, and only then close sockets; an unexpected stuck
test thread may be unblocked by shutting down its local socketpair.
Related malformed-request and cancellation tests also join before
closing. The preflight now validates numeric mount IDs, decimal
major:minor and the exact `-` separator position in mountinfo, including
negative tests for minimum-length malformed rows and positive tests
for optional fields and escaped paths. The NBD CI PR trigger now
covers the same relevant scripts as its push trigger.

**Executed CI evidence:**
https://github.com/k1moradi/swapz/actions/runs/37778788448
at `edbf6d1452bd8c87b36c44daa6ad349967592a22` concluded
**SUCCESS**. Static syscall isolation, Python compilation, the
complete rootless NBD selftest (including the previously blocked
partial-setup and worker-error mock assertions), three Bash syntax
checks, NBD teardown mock and streaming teardown mock all passed.
The workflow also ran **25 separate additional NBD selftest processes,
all 25/25 PASS**, for **26 successful complete selftests** total.
The log contained no EBADF or assertion tracebacks.

The NBD source is still **not independently Linux-host requalified**
against the new code by Codex, and real kernel attachment, teardown,
physical performance, live GC overlap and swap-in p99 remain untested.
The concurrent teardown source and kernel were not changed by this
NBD correction.

## 2026-10-08 — One-revision combined rootless teardown + NBD source gate PASS

The primary developer added
`.github/workflows/rootless-combined.yml` to require a *single exact
checkout* for the complete rootless teardown and NBD source suites,
rather than extrapolating an integrated verdict from unrelated CI
runs at different commits. The workflow is triggered by source,
fixture, or workflow changes on `main` and relevant pull requests.

**Executed CI evidence:**

- **Tested commit:** `8116bdfb8b61a69f67e6548904e82c191b979f23`
- **CI:** https://github.com/k1moradi/swapz/actions/runs/37779371716
- **Conclusion:** SUCCESS.
- **NBD source blob:** `768ff896e82198829cde83e28c8e0a35ddad368c`
- **Kernel blob:** `7589022ecdf0525716717270ab063a867a21f473`
- **Static NBD syscall isolation:** PASS before any selftest execution.
- **Bash syntax:** 10/10 (seven teardown and three NBD/streaming scripts).
- **DM/loop teardown mock:** PASS.
- **Pressure teardown mock:** PASS.
- **Offline GC latency analyzer:** 11 tests, OK.
- **NBD userspace compilation:** PASS.
- **Complete NBD selftest:** 1 initial PASS plus 25 additional
  independent process executions, **26/26 PASS**.
- **NBD DM teardown and streaming teardown mocks:** both PASS.

The test output includes the explicit
`NBD preflight, 8 MiB wire, setup cleanup and worker exceptions: PASS`
marker. Expected injected failure lines, including a Python
`NotADirectoryError` traceback from the real cgroup tri-state negative
test, do not imply gate failure: the corresponding rejection assertions
ran and the entire CI job concluded successfully.

**Scope:** all device-control commands were test-local mocks.
No real NBD attachment, DM/loop operations, swap commands, kernel
modules, physical backing or benchmark was executed. The previously
identified Bash PID inspection-to-signal TOCTOU limitation still exists.
Independent Codex Linux-host requalification of the latest teardown
source was assigned concurrently; this clean-runner gate does not
substitute for its result. Real NBD/GC latency and physical batch-size
qualification remain outside authorization.

## 2026-10-08 — Codex whitespace-only DM fail-open corrected and jointly revalidated

Codex independently tested teardown at
`5a3aea67fc303748c7efae7e4a36e595ba4c7ab7`. All ten standard
source-only commands passed, but a supplemental **rootless mocked**
`dmsetup ls --noheadings` response consisting only of whitespace was
incorrectly accepted as confirming target absence. Codex reported
**SOURCE-ONLY TEARDOWN GATE FAIL** despite the existing suite's green
result. The defect was the AWK rule `NF == 0 { next }`; Bash's normal
command substitution also stripped trailing newlines and could mask a
newline-only malformed inventory.

The primary developer fixed `swapz_test_confirm_dm_absent()` by:
- Preserving the exact trailing newlines from successful `dmsetup ls`
  output with an appended command-substitution sentinel.
- Rejecting any whitespace-only AWK record instead of skipping it.
- Feeding exact returned bytes to AWK without an inserted here-string
  newline, preserving a **truly empty** stdout as an accepted format.
- Retaining fail-closed behavior for malformed rows, duplicates,
  out-of-range device numbers, inventory failure and false-positive
  upper-target removal.

Rootless regression tests now cover spaces, tabs, newline-only output,
mixed valid/whitespace rows, malformed inventory after successful upper
removal, failed `dmsetup info`, and positive cases for empty stdout,
`No devices found`, valid unrelated target and target present.

Codex also found a pressure ControlGroup identity gap. The fixture now
explicitly passes `--slice=system.slice` to `systemd-run`, while
`swapz_pressure_cleanup_resources()` refuses any nonempty ControlGroup
other than the exact `/system.slice/$unit` path of each test-owned
service. Distinct unit names are required. Wrong, swapped, duplicated,
unrelated and traversal paths are tested; rejection leaves swap and DM
untouched. Empty cgroup metadata remains permitted only for a stopped
unit with MainPID 0 under the existing fail-closed checks.

For recall, the real fixture and rootless tests now share
`swapz_test_stop_children_then_cleanup_stack()`. The helper returns
failure without DM/loop cleanup if **any** of the three writer/reader
children cannot be stopped. Regression cases prove both the
unresponsive-child blocked path and successful upper/lower/loop cleanup
order. A nonnumeric `Used` field in `/proc/swaps` is additionally
rejected in the pressure negative suite.

**Executed evidence at identical revision:**
`3b60d7659df8cf59716286dfe0d1504307eb2e78`

- Rootless teardown workflow **SUCCESS**:
  https://github.com/k1moradi/swapz/actions/runs/37781726152
- Rootless combined NBD/teardown workflow **SUCCESS**:
  https://github.com/k1moradi/swapz/actions/runs/37781726172

The teardown workflow executed seven syntax checks, both full
teardown mocks including the new regressions, and 11 offline analyzer
tests. The combined workflow executed ten syntax checks, both teardown
mocks, the analyzer, static NBD syscall-isolation check, NBD userspace
selftest plus 25 process-level repetitions, and NBD/streaming teardown
mocks. Both succeeded on the **same** source commit.

**Qualification limits:** these remain source-only / rootless mocks,
not real NBD, DM, loop, swap or GC latency tests. The Bash jobs-to-PID
signal TOCTOU window remains; an atomic pidfd approach has not been
implemented or independently reviewed. Codex's concurrent independent
NBD Linux-host audit is a separate gate. The NBD backend and kernel
source blobs are unchanged by this teardown work.

## 2026-10-08 — Codex NBD impossible-dev_t preflight FAIL corrected

Codex independently ran the seven-command NBD source-only gate on its
Linux host at `b838ad11e7ac49327514d55a1f2aeea9e3e1769e`,
NBD source blob `768ff896e82198829cde83e28c8e0a35ddad368c`.
**All seven commands exited zero and ten independent selftests passed
without EBADF**, with syscall mock isolation checked first. Codex
nevertheless reported **NBD SOURCE-ONLY GATE FAIL** after finding that
the mountinfo parser accepted syntactically decimal but impossible
Linux device tuples such as `4096:0` or `43:1048576`, potentially
falsely proving the selected NBD node was unmounted. The partition
rejection branch also lacked a direct rootless selftest.

The primary developer updated `validate_nbd_node()` to parse mountinfo
device fields numerically, enforce the Linux 32-bit `dev_t`
major 0–4095 and minor 0–1048575 bounds, and compare numeric tuples
against the selected NBD identity (including leading-zero encodings).
Any malformed or out-of-bounds row anywhere in mountinfo fails closed.
It additionally reports inaccessible NBD partition enumeration as a
preflight error. Rootless negative/positive cases now cover:

- `4096:0` and `43:1048576` rejected;
- malformed negative minor and an out-of-range second row rejected;
- valid unrelated `4095:1048575` and `0:0` accepted;
- a selected-device mount with `0043:000` rejected;
- synthetic `nbd0p1` child rejected and unreadable partitions rejected;
- empty partition list retained in the existing positive preflight cases.

**Executed same-revision GitHub Actions results:**

- Source commit `40678c7d9743d6efca943885f40be1a0388d3ca6`.
- Rootless NBD CI **SUCCESS**:
  https://github.com/k1moradi/swapz/actions/runs/37783419565
  — static syscall-isolation gate, Python compile, complete NBD
  selftest plus **25/25 independent additional selftests**, three
  shell syntax checks and both rootless NBD/streaming teardown mocks.
- Combined rootless teardown+NBD CI **SUCCESS**:
  https://github.com/k1moradi/swapz/actions/runs/37783419522
  — same commit, ten Bash syntax checks, two full teardown mocks,
  11 offline GC analyzer tests, static NBD syscall isolation,
  NBD compile, **26 complete NBD selftests** (one plus 25 repeats)
  and both NBD/streaming teardown mocks.
- No EBADF or selftest assertion failure appeared in either run.
  The complete selftest reached its partial-setup cleanup and
  unexpected worker-exception checks.

The NBD kernel-worker shutdown still contains the deliberate unbounded
join to preserve active descriptors; no real kernel NBD driver
termination was tested. The kernel and teardown source were unchanged
by this NBD patch. Codex independent Linux-host requalification of the
updated NBD blob remains to be obtained after its separate teardown
audit. No actual DM, loop, NBD, swap, module, physical-media or
benchmark operations were authorized or performed.

## 2026-10-08 — Codex teardown PASS and follow-up systemd guard coverage

Codex independently validated teardown at
`0f2f169631d08fc1b92e2aba1bed398e1ef795ff` and reported
**SOURCE-ONLY TEARDOWN GATE PASS**: seven Bash syntax checks, both
rootless teardown mocks, and all 11 offline GC analyzer tests exited
zero. Supplemental shell-local inventory checks confirmed that the
whitespace-only DM fail-open was closed and that the command-substitution
sentinel preserves both inventory bytes and failure status. Codex found
no new P0 fail-open issue. It identified P2 checked-in regression gaps
for malformed/duplicate unit names and empty ControlGroup combined
with an active state or nonzero MainPID.

The primary developer added corresponding mock cases, including
duplicate, empty, nonsuffixed, traversal, slash and illegal-character
unit names; empty ControlGroup with MainPID > 0 or ActiveState=active;
and accepted empty ControlGroup with MainPID=0 and
ActiveState=inactive or failed. All rejection cases begin with modeled
active swap and assert no swapoff, no DM/loop cleanup, unchanged swap
state and no unexpected process signal.

A new file-backed `systemctl show`/signal event log proves those
negative cases reach the intended production guard despite Bash
command substitutions, which isolate in-memory mock counters. Tests
assert the exact four-property inspection sequence for rejected empty
cgroups and no systemd calls for invalid unit names.

The new tests revealed a sequencing gap: production cleanup validated
each name just before processing that unit, allowing a malformed
SECOND_UNIT to be detected after the first unit was already touched.
The production helper now prevalidates **both** names before any
systemd call. This was a separate narrow correctness fix, not a change
to swapoff or block-device cleanup ordering.

**Executed rootless CI at the same source commit**
`e64509318576f3c4d65050426af234c2910b70ff`:

- Teardown safety **SUCCESS**:
  https://github.com/k1moradi/swapz/actions/runs/37784883620
  — seven Bash syntax checks, complete DM/loop and pressure regression
  suites, and 11 offline analyzer tests.
- Combined NBD and teardown **SUCCESS**:
  https://github.com/k1moradi/swapz/actions/runs/37784883592
  — same regression suites, 10 Bash syntax checks, static syscall
  containment gate, NBD compilation, one complete NBD selftest and
  25 additional separate selftest processes (**26/26 PASS**), plus
  NBD/streaming teardown mocks.

The intermediary CI run at `41adbff877cf609634778829b36276d4404521b2`
correctly failed because the first production unit could be contacted
before rejecting an invalid second unit. The above fix and subsequent
successful workflows resolved that regression.

The shell-owned-child jobs-to-PID inspection/signaling TOCTOU remains
a design qualification, not an issue solved by these mocks. Independent
Codex host requalification of the latest NBD source is being performed
separately. No real systemd unit, DM, loop, NBD, swap, module, fio,
physical-media test or reboot was performed.
