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

## 2026-10-08 — Exceptional 8 MiB NBD socketpair cleanup: deterministic rootless coverage

Codex independently reported **NBD SOURCE-ONLY GATE PASS** on
`bd9fac18d06f1c4642c913618de645401611698e`, NBD source blob
`3138df5d431b086ad61a4debda04159f6e0a6010`: all seven required
commands and ten additional timed Linux-host selftests passed.
Its remaining P2 finding was an unexercised exceptional 8 MiB
test-local socketpair path after two bounded worker joins. No P0 or
NBD source-only blocker was found.

The primary developer extracted **test-only**
`finish_test_socketpair_worker()`, used by the full 8 MiB wire
selftest. It sets the stop event, joins for at most two seconds,
requests local client socket shutdown if still alive, and joins again
for at most two seconds. Both test-local sockets close in a
`finally` block. If the worker remains alive **after the second join**
the function raises an explicit `AssertionError` even if later
socket closure happens to unblock it. Recorded worker exceptions also
fail the test. It does not force Python threads to terminate or change
production `serve_kernel()` / kernel-session descriptor protection.

`selftest_socketpair_cleanup()` uses fake workers, sockets and a stop
event to deterministically check first-join exit, second-join exit,
socket-shutdown OSError, still-alive failure with diagnostics,
unexpected worker exception, unstarted cleanup and preservation of a
wire-transaction exception. Assertions check stop/join/close order,
finite join timeouts and closure of both sockets without creating
an indefinitely running test thread.

**Executed CI at one exact commit**
`52a2d6330428c64b39f2f8fe1c42aa1ff70a4cc9`:

- NBD source-only **SUCCESS**:
  https://github.com/k1moradi/swapz/actions/runs/37788553329
  — static syscall isolation, compilation, full NBD test, 25 further
  complete process-level selftests (**26/26 PASS**), three shell syntax
  checks and NBD/streaming teardown rootless mocks.
- Combined NBD/teardown **SUCCESS**:
  https://github.com/k1moradi/swapz/actions/runs/37788553094
  — same source, ten Bash syntax checks, complete DM/loop and pressure
  rootless suites, 11 offline GC analyzer tests, NBD isolation, full
  NBD test plus 25 repetitions (**26/26 PASS**), and two teardown mocks.

Both logs include `NBD 8 MiB socketpair fault-injected cleanup: PASS`
and the full wire/setup/worker-exception PASS. No EBADF or assertion
failure was observed. The still-alive test case *intentionally* raises
and catches an AssertionError to prove it cannot be treated as
success; it does not simulate actual unkillable threads.

Separately Codex's independent teardown gate passed on
`0f2f169631d08fc1b92e2aba1bed398e1ef795ff`. The newer
systemd unit-name prevalidation has passed integrated CI, but is
being separately audited by Codex together with a **design-only**
review of the remaining shell PID check-to-signal reuse window.
Source-only tests are not proof of actual kernel NBD execution,
GC-overlap swap-in p99 or measured physical throughput. No actual
block device, systemd pressure workload, swap or module activity was
performed.

## 2026-10-08 — Pressure checkpoint PID-signaling migration, source-only CI PASS

Following Codex's **SOURCE-ONLY TEARDOWN GATE PASS** and its
independent PID-reuse design review, the primary developer removed the
pressure fixture's numeric-MainPID signal paths. The prior
`pressure-helper.py` held at two `os.kill(os.getpid(), SIGSTOP)`
checkpoints, `pressure.sh` resumed its saved MainPID twice with
`kill -CONT`, and `pressure-teardown.sh` could manually resume that
MainPID after a non-atomic `/proc/<pid>/cgroup` ownership check.

**New source-only protocol:**

- The pressure helper publishes `filled` and `verified` markers
  only after the respective fill and readback operations. It retains
  the allocated memory while awaiting each phase release.
- The fixture uses a new private directory per unit and a fresh
  128-bit random hex nonce. A matching `phase:nonce` token is
  required for each release; `release-filled` cannot satisfy
  `release-verified`. Marker validation is exact.
- `pressure_checkpoint.py` atomically publishes complete marker
  and release data via temporary files and `os.link` with
  no-replace semantics, rejecting stale or duplicate files rather
  than silently overwriting them. Waits use a monotonic deadline,
  a short polling interval and an explicit timeout; malformed
  release tokens fail immediately.
- `pressure.sh` no longer uses `ps` job state or numeric-PID
  `kill -CONT` to advance checkpoints. It preserves the memory,
  /proc/swaps, DM status, GC-page and readback checks between
  releases, plus finite unit-completion waits.
- `swapz_pressure_cleanup_resources()` still validates both
  distinct unit identities before contacting systemd, stops each
  named unit and verifies cgroup quiescence, swap inactivity and
  dependency order, but no longer resumes a saved numeric MainPID.
  Its read-only MainPID check remains for guarding the empty-cgroup
  case.

**New rootless regression:** 8 `pressure-checkpoint-test.py`
unit tests exercise both phases, wrong-phase/cross-unit nonce,
duplicate/stale/malformed release, deadline, interruption, retained
positive completion, readback corruption and pre-verified failure.
The pressure cleanup mock now explicitly requires no numeric-PID
signal even with nonzero MainPID and confirms stop/verify/swapoff/
mapper removal ordering.

**Successful source-only CI on exact tested HEAD**
`1c5cfe5305ba0bad9c8edbf404390b4093bdfbec`:

- Teardown workflow: https://github.com/k1moradi/swapz/actions/runs/37791843695
  — seven Bash syntax checks, DM/loop and pressure regressions, Python
  compile, eight release-token tests and 11 offline analyzer tests.
- Combined workflow: https://github.com/k1moradi/swapz/actions/runs/37791843564
  — same pressure tests, ten Bash checks, two teardown regressions,
  11 offline GC analyzer tests, NBD syscall isolation, compile,
  **26/26 complete NBD selftests** (one plus 25 repetitions) and two
  NBD/streaming teardown mocks.

The first CI run with these tests failed because the test expected
`ValueError` for a release attempted before its marker existed.
The implementation correctly raised `FileNotFoundError`;
the assertion was corrected, and both complete CI workflows passed.

**Limits:** this is a rootless token and mocked teardown gate; the
actual 160/32 MiB pressure fixture has NOT been executed, and live
systemd behavior, swap-in latency, GC overlap and physical device
behavior remain unverified. The separate recall Bash job-to-kill PID
reuse race is still open. Codex is independently prototyping a gated
pidfd supervisor for recall; that prototype is NOT integrated here.
No real systemd service, NBD/DM/loop device, swap command, module,
fio, physical backing or reboot was exercised.

## 2026-10-08 — Pressure checkpoint file-type and bounded-read hardening

A follow-up source-only audit found that pressure release/marker checks
used `Path.read_bytes()`: valid-looking contents could be read through
a symlink, a FIFO read could block, and a very large file could be read
without a bound. The pressure fixture also used shell `cat` to inspect
its `filled` and `verified` marker, duplicating those hazards.

`tests/runtime/pressure_checkpoint.py` now validates each token via
`lstat`, a no-follow/nonblocking descriptor open, `fstat`, exact
file/inode identity, regular-file and single-link checks, expected
byte size, and a bounded read of at most the expected token length
plus one. This rejects malformed files rather than treating them as
checkpoint progress. The controller provides a read-only `check`
command used for both marker phases in `pressure.sh`; token release
still uses the original atomic, no-overwrite publication and fresh
nonce check.

Eight new rootless cases (16 total) verify symlinks to *valid* marker
and release contents cannot spoof readiness, FIFO marker and release
cannot block, oversized token files fail without an unbounded read,
hardlinked markers are rejected, controller CLI validation does not
publish releases, and a token replaced between `lstat` and open is
rejected. Existing phase, timeout, interruption, readback-corruption
and correct release tests remain intact.

Both CI workflows additionally repeat the full 16-test pressure
suite in **ten independent timed processes** to catch concurrency
and scheduling regressions.

**Executed source-only results:**

- Teardown rootless workflow **SUCCESS** at
  `6755e82b18c59f9b9047098ec6da97dba620c3f6`:
  https://github.com/k1moradi/swapz/actions/runs/37794454277
  — 16 pressure token tests, 10/10 additional timed suite runs,
  DM/loop and pressure teardown regressions, seven Bash syntax
  checks and 11 offline analyzer tests.
- Latest combined rootless workflow **SUCCESS** at
  `45ac8b7dc668200315bea8556708bffa944dcb3d`:
  https://github.com/k1moradi/swapz/actions/runs/37794468550
  — the same 16 tests and 10/10 pressure repeats, all teardown
  regressions, 11 offline analyzer tests, NBD syscall isolation,
  compilation, **26/26 complete NBD userspace selftests** and
  NBD/streaming mock teardowns. The two source commits differ
  only by the follow-up combined workflow change.

A traceback line in each teardown/combined log is the pre-existing
expected injected cgroup-directory type failure, not a real test
failure; both jobs ended `success`. These are private temporary-file
and rootless mocked tests, **not** a real systemd pressure, swap or
block-device qualification. The Codex pidfd supervisor prototype
remains separately assigned and unintegrated; recall PID reuse is
not resolved by these changes.

## 2026-10-08 — Production pressure controller isolated and explicitly fail-closed

A source-only review identified that the pressure fixture's `run_pressure()`
was embedded after real DM/loop/swap initialization, preventing isolated
execution of the actual phase controller. Existing tests validated
`pressure_checkpoint.py` and teardown independently, but not the
controller's sequence of checking `filled`, releasing the helper,
validating `verified` accounting, and releasing completion.

The primary developer moved that controller verbatim into the
source-only `tests/runtime/pressure-runner.sh` as
`swapz_pressure_run_unit()`, sourced by `pressure.sh`. Sourcing the
library takes no device action. New
`pressure-runner-regression.sh` calls the **same production function**
with shell-local mocks of `systemd-run`, `systemctl`, cgroup reads,
`/proc/swaps`, `dmsetup status`, and bounded polling. The only
permitted actual Python subprocess is the rootless private-file
checkpoint CLI. No pressure fixture, live unit or block/swap command
runs.

**Safety defect found by the new regression:** when a Bash function is
called via a conditional (`if`, `||`), `set -e` inside the function
does not reliably abort on intermediate failed commands. The
production controller could continue after a zero `memory.swap.current`
arithmetic check and issue `release-verified`. The rootless regression
reproduced this actual branch failure before the fix.

The controller now uses **explicit guarded returns** for unit launch
and directory creation, cgroup and DM-status reads, phase polling,
`/proc/swaps` observations and status processing. Verified accounting
requires strictly decimal, **positive** memory swap and active-swap
used values, an exact `failed=0` status field, and positive
`gc_pages` when GC is required. Failed or unreadable inspection
cannot authorize the second release, regardless of Bash's caller
`errexit` context.

The 17 rootless controller scenarios (two successful variants and 15
negative/failure variants) exercise missing, wrong and symlink/FIFO
markers; malformed unit ControlGroup, early exit and missing phase
markers; zero memory or swap usage, failed/unreadable DM status,
zero required GC pages, and unsuccessful unit result. The regression
asserts that failures cannot publish inappropriate phase releases.

The existing `pressure-checkpoint-test.py` static assertions now
verify the real fixture sources and invokes the extracted controller,
so the library tests cannot silently become disconnected from runtime.

**Successful source-only CI at identical commit**
`c484ac0c9a90c5ff33b0c17b2b1044f5be80110d`:

- Teardown **SUCCESS**:
  https://github.com/k1moradi/swapz/actions/runs/37801182069
  — shell syntax, actual controller with mocked dependencies,
  DM/loop and pressure teardown regressions, 16 token tests with
  10 additional timed suite repetitions, and 11 offline analyzer tests.
- Combined **SUCCESS**:
  https://github.com/k1moradi/swapz/actions/runs/37801181958
  — same pressure and teardown gates, NBD static syscall isolation,
  compilation, 26 complete NBD socketpair/userspace selftests, and
  NBD/streaming teardown mocks.

Intermediate CI failures identified initial regression-mock
argument parsing and a static assertion still looking in
`pressure.sh` after the extraction. Those were corrected. The new
runner then exposed the genuine zero-memory-swap fail-open, which
was fixed and requalified in both passing runs.

**Boundary:** real systemd, swap pressure, device/mapper setup and
live-GC behavior remain untested and unauthorized. Codex's separate
gated-pidfd supervisor for recall is still not integrated; this
pressure controller work does not eliminate the recall PID-reuse risk.

## 2026-10-08 — Strict pressure /proc/swaps accounting and checkpoint release safety

While Codex independently works on recall's gated-pidfd supervisor,
a source-only pressure controller review found another **fail-open
accounting ambiguity**: `awk '$1==d {used=$4} END {print used+0}'`
silently converted a malformed `Used` field such as `16garbage`
to a positive number; a missing target swap was silently represented
as zero rather than reported as malformed. The filled checkpoint
also previously only printed matching inventory rows.

The primary developer added `tests/runtime/pressure-swap-inventory.py`
and replaced those AWK inspections in the production
`swapz_pressure_run_unit()` at **both** filled and verified phases.
The strict parser verifies the full `/proc/swaps` header and *every*
inventory row (five fields, absolute path, file/partition type,
bounded ASCII-decimal Size/Used/Priority, nonzero Size and Used ≤ Size).
It requires exactly one row whose canonical device path matches the
test's known canonical swap device, rejecting absent/duplicated
targets, malformed unrelated rows and truncated inventories.
No `used+0` conversion or default fabricated zero is used.
At verified checkpoint, the existing positive-memory-swap,
positive-Used, exact `failed=0` DM status and required-GC predicates
still gate release; unreadable or malformed inventories now stop
progress at either checkpoint.

**Rootless regression additions:** 23 dedicated parser unit tests
exercise accepted target/unrelated entries, zero Used for the early
phase, negative priority, valid canonical symlink aliases, and failures
for missing/duplicate target, malformed header/rows/numerics,
Unicode digits, oversized numbers, missing final newline, impossible
Size/Used, invalid type/path and malformed unrelated entries.
The rootless *production controller* regression also invokes the
actual parser through a synthetic file while mocking systemd, cgroups
and DM, checking that missing, duplicated, corrupt-Used, corrupt-header
and corrupt-unrelated swap inventories prevent checkpoint release.
This remains completely separate from actual pressure workload
execution or real swap commands.

**Successful source-only GitHub Actions evidence:**

- Teardown rootless gate **SUCCESS** at
  `3f4d1cd334074ba423b87b0801b1bccd72d0021c`:
  https://github.com/k1moradi/swapz/actions/runs/37802473498
- Combined rootless gate **SUCCESS** at
  `b3833393c2a6d4e351e2610e647eaad0863eed05`:
  https://github.com/k1moradi/swapz/actions/runs/37802481882

Both runs exercised the same parser/controller source blobs;
the latter revision includes a combined-workflow step to run the
23 parser tests. The final combined gate passed 23 swap-parser
tests, the full rootless controller and pressure/DM teardown
regressions, 16 pressure checkpoint tests with 10/10 additional
timed repetitions, all 11 offline GC analyzer tests, static NBD
syscall isolation and **26/26 complete NBD userspace selftests**.
There were no unexpected assertion failures or `EBADF` results.

**Limits:** all inventories in the new parser and controller tests
were synthetic regular files. No live /proc/swaps modification,
systemd pressure job, kernel device, real swapoff/on, GC-overlap
latency or physical performance test occurred. The recall PID-reuse
risk is not addressed by this pressure change. The kernel, NBD
backend, and Codex-owned recall/DM teardown source remain unchanged.

## 2026-10-08 — Fixture-neutral direct recall I/O plan and mandatory pidfd prototype CI

After Codex pushed the independent gated-pidfd supervisor prototype
at `5cb92f6696232f1719cfc9390f77b109a2d00c23`
(supervisor blob `52ebf3d700a49c4396a2236b4137d334641012d0`),
the primary developer added a **new fixture-neutral** direct recall
orchestration prototype in `tests/runtime/recall-io-plan.py`.
This does **not** replace or execute `buffer-recall.sh`.

The plan accepts an injected supervisor with `launch(argv)`,
`wait(opaque_handle, finite_timeout)` and `stop_all(handles)`.
It prepares each expected 4096-byte page from the original nine-page
source, constructs **direct `dd` argv arrays** (not Bash child
functions or `bash -c`), launches and waits for the sequential
Buffer A/Buffer B reads, and **launches both concurrent reads before
waiting for either**. Exact-data comparisons run synchronously after
worker exit/reap confirmation; a controlled monotonic clock supports
timing-order assertions, not claims about real device latency.

Every successfully returned opaque handle remains in the registry,
even after a successful wait, including the nine-page direct writer,
which stays outstanding through the read checks. A failed or
ambiguous launch, wait, comparison, worker identity, or supervisor
connection prevents the plan's cleanup callback; `stop_all` is
still called to account for known workers when possible. Positive
cleanup requires an explicit all-reaped, cleanup-allowed report.
This is conservative **source-only** orchestration and does not
prove descendant containment or production stop behavior.

A new `tests/runtime/recall-io-plan-test.py` suite uses only a
synthetic nine-page temporary file and fake supervisor: **25 tests**
cover exact 4 KiB expected/output comparisons, direct writer/read
argv, launch-before-wait ordering, staged writer lifetime, retained
handles, launch/second-launch/wait/reap failures, corrupted or missing
read outputs, duplicate/mismatched handles, supervisor disconnection,
denied callbacks and admitted success. An AST check verifies that the
plan does not invoke process-creation or numeric-signal APIs.
No test opens a mapper or spawns a real dd process.

The teardown and combined rootless GitHub workflows now **require**
Codex's standalone supervisor regression: syntax compilation,
**27 full tests**, and **3 additional independent runs** each
bounded by a 40-second process timeout. They also require the new
25-test direct recall plan, preserving existing pressure/DM/NBD gates.

**Both workflows succeeded at exactly the same commit**
`a276218feba2454b5f4c1e9c515d276a8155c468`:

- Teardown: https://github.com/k1moradi/swapz/actions/runs/37808199284
  — 27 supervisor tests plus 3/3 repeats, 25 direct I/O plan tests,
  both teardown mocks, 23 strict swap-parser tests, 16 pressure
  token tests and 10/10 repeats, and 11 offline GC analyzer tests.
- Combined: https://github.com/k1moradi/swapz/actions/runs/37808199250
  — all above plus NBD syscall-isolation check, compilation,
  **26/26 complete NBD selftests** and NBD/streaming teardown mocks.

An earlier first-pass CI run failed because the new test incorrectly
matched the string `shell=True` in a non-executable comment. The test
was changed to inspect Python AST for executable process-spawning
calls instead; the two completed CI runs above passed. There was no
device or process-safety bypass in the source.

**Unresolved P1:** `buffer-recall.sh` still uses Bash job PIDs for
SIGCONT/SIGTERM and background `read_page` wrapper functions.
The new plan and Codex's gated-pidfd prototype are **not connected
to production recall**, nor to the unfinished separate IPC service.
Production migration needs a reviewed control-channel adapter,
failure-aware teardown and descendant containment. No real DM,
loop, NBD, swap, systemd unit, module, physical-media test, fio,
recall fixture, pressure fixture or reboot was performed.

## 2026-10-08 — Rootless recall reference/readback file-safety qualification

While Codex separately develops the pidfd supervisor IPC service, the primary
developer hardened the **fixture-neutral, not-yet-integrated**
`tests/runtime/recall-io-plan.py` reference and readback handling.
Previously `Path.exists()` missed dangling symlinks and
`Path.write_bytes()` could follow a racing link while creating the
expected page; unrestricted `Path.read_bytes()` could follow a symlink,
block on a FIFO or allocate memory for an oversized result. An exact-byte
comparison alone did not establish the file's type or ownership identity.

The new `_read_exact_regular()` rejects symlinks, FIFO/special files,
hardlinks, wrong-length content and paths replaced between `lstat` and
`open`. It uses `O_NOFOLLOW | O_NONBLOCK | O_CLOEXEC`, compares
pre-open and post-open device/inode and regular-file/link-count metadata,
enforces exact expected length and reads no more than one page plus one
byte. The nine-page fixture source must also be an exact-size regular
single-link file. The expected 4096-byte reference uses
`O_CREAT | O_EXCL | O_NOFOLLOW` to prevent replacing or following an
existing or newly injected file. Path preparation and readback failures
record `plan.failure`, preventing the future cleanup callback even
after a successful supervisor stop report.

The fake-supervisor rootless regression gained **12 adversarial tests**
(37 total) for dangling symlinks and FIFOs existing before worker
launch; symlinked/hardlinked source, symlinked, hardlinked, FIFO,
undersized or oversized readback, symlinked expected data after worker
reaping, injected exclusive-create racing link, and inode replacement
between lstat and open. All tests use disposable regular files and
fake workers; there are no production `dd` invocations, device
accesses, real PID signals, or block-device teardowns.

**GitHub Actions SUCCESS at exact code commit**
`4181df6ad91099ae0717fa6474750be153ed8734`:

- Rootless teardown:
  https://github.com/k1moradi/swapz/actions/runs/37809491958
- Combined NBD and teardown:
  https://github.com/k1moradi/swapz/actions/runs/37809491946

Both workflows passed **37 recall I/O plan tests**, **27 gated pidfd
supervisor tests**, three further complete supervisor test processes,
the teardown mocks, 23 strict pressure swap-parser tests, 16 pressure
checkpoint tests with 10 independent repeats, and 11 offline GC
analyzer tests. The combined workflow also passed static NBD syscall
isolation, compilation, 26/26 full NBD selftests and both NBD/streaming
teardown mocks.

The initial code-only commit's CI failed solely because the pre-existing
test still expected a diagnostic containing `truncated` after the
file-size guard began reporting `invalid recall file identity or size`.
That assertion was updated alongside the 12 negative cases before the
successful runs above.

This strengthens the synthetic I/O plan, **not** production
`buffer-recall.sh`. Numeric-PID signaling remains in that live fixture
until IPC service integration and independent review. The kernel, NBD
source, DM/loop teardown, production recall, pressure code and Codex
supervisor files were not changed; no real device, systemd/swap,
physical-media or latency experiment occurred.

## 2026-10-08 — Trusted recall references and worker cleanup-report attestation

A source-only review found two risks in the future, not-yet-integrated
`tests/runtime/recall-io-plan.py`:

1. **Reference poisoning:** the controller previously compared two
   on-disk files (`expected` and `readback`). If both were overwritten
   with the same incorrect 4096-byte contents after preparation, the
   comparison could pass. Each prepared page is now retained as a trusted,
   immutable in-memory bytes value; both on-disk expected and worker
   readback must match that original byte value.
2. **Conflicting supervisor report:** a top-level `cleanup_allowed=True`
   and `all_reaped=True` could previously authorize a cleanup callback
   even if a detailed result omitted a registered handle, duplicated or
   added an unknown handle, contained per-worker errors, reported an
   unreaped worker, or contained report-level errors. The adapter now
   independently verifies exact registered-handle coverage, distinct
   identities, all worker reaped flags, absence of worker/report errors,
   and both positive top-level safety decisions. Missing or invalid
   report details fail closed.

These changes are limited to the isolated plan and its rootless
fake-supervisor tests; they do not modify `buffer-recall.sh`, the
supervisor prototype, or Codex's in-progress IPC service.
Nine new rootless negative cases (46 total) cover identical corruption
of expected/readback, corrupted expected data alone, contradictory
summary/report errors, missing, unknown or duplicate result handles,
worker errors, unreaped workers and missing detail records. The
existing 37 tests continue to cover direct `dd` argument planning,
concurrency ordering, exact pages, source/readback file type and
inode validation, and failed-stop cleanup denial.

**Same-commit rootless CI PASS at**
`ec70195d1d1c7a44a72aea83de65043c5fef323f`:

- Teardown:
  https://github.com/k1moradi/swapz/actions/runs/37810629055
  — 46 recall I/O plan tests, 27 supervisor tests and 3/3 repeats,
  rootless DM and pressure regression suites, 23 strict swap-parser
  tests, 16 pressure token tests and 10/10 repeats, and 11 offline
  GC analyzer tests.
- Combined:
  https://github.com/k1moradi/swapz/actions/runs/37810628795
  — same recall/pressure/teardown checks plus static NBD syscall
  containment, Python compilation, **26/26 full NBD userspace
  selftests** and NBD/streaming teardown mocks.

The initial source-only commit with strict stop-report checking failed
the recall-plan mocks because their old `FakeReport` did not expose
detailed worker results. The mock was updated to model the real
supervisor's full report contract; both complete workflows then passed.
This is a deliberate fail-closed API hardening, not a live IPC proof.

**Limits:** real production recall still uses numeric-PID Bash job
signaling and can have untracked descendant workers; the new IPC
service is not integrated. No real DM/loop/NBD, swap, systemd,
kernel module, fio, physical device or pressure/recall workload
operations were performed.

## 2026-10-08 — Rootless pidfd IPC adapter and mandatory service gate

Codex previously delivered a **test-only** single-threaded pidfd
supervisor IPC service, with a private inherited Unix socket,
bounded length-prefixed frames, 23 standalone protocol/lifecycle
tests and fixed `sleep`/`exit` worker allowlist. Production
`buffer-recall.sh` was not wired to the service.

The primary developer added a new, separate
`tests/runtime/recall-ipc-adapter.py` and
`tests/runtime/recall-ipc-adapter-test.py`. The adapter does NOT
accept generic argv, real `dd` workers or mapper paths. It
tracks opaque handles returned from the service and verifies each
test-worker wait result. It independently reconciles `stop_all`
against the **exact complete handle set**, rejects missing,
duplicate or unknown workers, unconfirmed reap, worker/report errors,
invalid fields and contradictory summary flags. Cleanup denial
is sticky. A synthetic callback cannot run until successful
`stop_all`, successful `shutdown`, the actual service process
exiting with code zero, and explicit client exit confirmation.
This is distinct from Codex's concurrent independent IPC client
safety review; it makes no changes to the service/client source.

The adapter's **20 rootless tests** include fake malformed,
contradictory, incomplete or stale response cases; invalid launch
and wait; duplicate handles; nonzero and unconfirmed worker
exit; service-process failure and timeout; and actual private
socketpair subprocess sessions with only short-lived owned
`sleep`/`exit` test workers. The tests demonstrate that
two workers may be launched before either wait, that a valid
stop/shutdown/exit sequence permits a **synthetic only** callback,
and that connection loss before or after stop or failed worker
execution preserves backing authorization denial.

The two existing GitHub Actions source-only gates now require
compilation and execution of the **23-test IPC service regression**
plus **10 additional separate timed complete test-suite processes**
(`timeout 15s` each), followed by the 20-test adapter regression.
The prior 27-test gated pidfd supervisor with 3 repetitions, the
46-test unintegrated direct recall I/O plan, pressure and DM teardown
regressions, strict swap inventory, checkpoint token tests and NBD
gates remain required.

**Successful same-revision CI at exact code HEAD
`d6a92486d71ba0e1f6c27cf1c1b4781e4ce1cd81`:**

- Rootless teardown **SUCCESS**:
  https://github.com/k1moradi/swapz/actions/runs/37814381219
  — 23 IPC service tests, **10/10 timed repeats**, 20 adapter
  tests, 27 supervisor tests and **3/3 repeats**, 46 recall
  I/O plan tests, 23 strict swap inventory tests, 16 pressure
  token tests and **10/10 repeats**, rootless teardown regressions
  and 11 offline GC analyzer tests.
- Combined source-only **SUCCESS**:
  https://github.com/k1moradi/swapz/actions/runs/37814381190
  — same tests plus static NBD syscall containment, compilation,
  **26/26 complete NBD selftests** (one full selftest and 25
  additional complete runs) and NBD/streaming teardown mocks.

The first new adapter gate failed because a fake test-response
constructor inadvertently supplied duplicate `ok` arguments.
The test fixture was corrected and both full workflows completed
successfully; no production source was changed by that correction.

**Explicit limitations:** this adapter uses only fixed test-worker
commands and cannot launch direct `dd`. The real recall
`buffer-recall.sh` still tracks numeric Bash child PIDs and uses
background read-function wrappers that may spawn untracked mapper
I/O workers. Its check-to-signal PID-reuse risk is **not solved**.
The adapter and Codex's service were tested together for controlled
rootless test workers; production direct-I/O allowlisting, IPC
migration, descendant containment and independent safety review
remain separate milestones. No actual DM, loop, NBD, swap, systemd,
kernel module, fio, physical-device or recall/pressure fixture
operation was performed.

## 2026-10-08 — Strict fixture-bound direct-dd role allowlist

While Codex separately audits the pidfd IPC cleanup-authorization
protocol, the primary developer implemented a **standalone proposed
direct-`dd` launch allowlist** in
`tests/runtime/recall-dd-allowlist.py`. It does not edit or connect
to `test-child-supervisor-service.py`, the direct I/O plan, or
production `buffer-recall.sh` and never launches `dd`.

The trusted launcher binds the exact fixture root and
`swapz-v22-recall-<test-specific-name>` mapper identity before any
client request. Only five fixed, one-use roles may produce argument
vectors: the nine-page direct writer and four 4096-byte staged
Buffer A/B reads at page offsets 0, 4, 0 and 5. Exact `dd` argv
includes every source/destination, block size, count, offset,
direct-I/O/conv flag and status argument. Role replay,
reader-before-writer, arbitrary argv, shell options and target
redirection permanently close admission. The policy checks a
canonical absolute test-owned directory, single-link exact-sized
36,864-byte `pages.bin`, retained root/source dev-inode identity,
and absence of any pre-existing output including dangling links
and FIFOs. All path inspections are read-only and **no**
`/dev/mapper` device is opened.

Twenty-six new rootless
`tests/runtime/recall-dd-allowlist-test.py` cases exercise
the five exact commands and their byte-for-byte agreement with
the existing fixture-neutral I/O plan, extra/modified argument
rejection, mapper grammar, malformed paths, symlinked ancestors,
source symlink/hardlink/FIFO, short or oversized source, replaced
root/source inode, stale output paths, one-use launch and sticky
denial. New CI workflow steps require compile and execution of
this suite. An initial rootless run found that a missing fixture
path raised raw `FileNotFoundError`; the policy was adjusted to
normalize inspection failure into explicit `DDPolicyDenied`
before the final two green runs.

**Source-only PASS at identical executable-code revision
`8aa82dfef9a455ee3e6b26e7e3533c2eb98758d3`:**

- Rootless teardown:
  https://github.com/k1moradi/swapz/actions/runs/37815480268
- Combined NBD/teardown:
  https://github.com/k1moradi/swapz/actions/runs/37815480464

Both passed 26 allowlist cases, 20 IPC adapter tests,
23 IPC service tests plus 10 complete repeats,
27 pidfd supervisor tests plus 3 repeats,
46 direct recall plan tests, 23 strict pressure swap parser tests,
16 pressure token tests plus 10 repeats, and 11 offline analyzer
tests. The combined gate also passed static NBD syscall isolation,
NBD compilation and **26/26 full NBD protocol selftests**, plus
teardown mocks. All these are private temporary-file and rootless
mock checks.

The threat model and outstanding production integration requirements
are documented in `docs/recall-dd-allowlist.md`. **Critical
limitation:** this policy does not bind file descriptors through
`exec`; it cannot eliminate a path replacement race after checking
but before a future worker opens its path. The future trusted
launcher must bind its owned private directory, source, output
paths and mapper identity at the actual execution boundary.
No live DM, loop, NBD, swap, systemd, physical device, recall
fixture, kernel module or benchmark operation occurred. Production
numeric-PID recall cleanup is unchanged.

## 2026-10-08 — Persistent test-only Bash-to-pidfd IPC control bridge

While Codex separately works on the reviewed direct-`dd` role-admission
and launch-boundary safety, the primary developer added a rootless
Bash-facing persistent bridge in `tests/runtime/recall-control-bridge.py`
plus `recall-control-bridge-test.py` and
`recall-control-bridge-regression.sh`. The bridge creates a private
socketpair, owns one subprocess running the test-only pidfd control
service, binds that exact `Popen` instance to
`SupervisorControlClient` and retains the existing
`RecallIPCAdapter` from launch through `STOP_ALL`, `SHUTDOWN`
and `FINALIZE`. It does not modify production `buffer-recall.sh`.

Bash's restricted newline-JSON interface has bounded 2048-byte
requests, strictly increasing request IDs and exactly five
operations: `LAUNCH_TEST` (fixed `sleep`/`exit` workers only),
`WAIT` (registered opaque handle), `STOP_ALL` (complete internal
handle inventory), `SHUTDOWN` and `FINALIZE`. It refuses
caller-supplied argv, device paths, numeric PIDs, arbitrary
process signals, omitted/duplicate worker handle overrides,
unknown fields, duplicate JSON keys, truncated/oversized
requests and command replay. It never executes `dd`, a real
DM operation or any swap/device command.

**Cleanup authorization is delayed until FINALIZE**. Every
prior reply, including successful `STOP_ALL` and `SHUTDOWN`,
explicitly says `cleanup_allowed=false`; `FINALIZE` requires
a complete stop/reap attestation, successful service shutdown,
actual matching zero service-process exit and clean closure of
the control socket. A failing worker, malformed frame, bad
channel/descriptor, premature EOF, unsupported operation or
unconfirmed service exit returns a preservation verdict and
nonzero status whenever possible. No numeric-PID signal
fallback exists; disconnection triggers best-effort control-socket
closure/reap, which must never count as cleanup authorization.

The **23-test rootless Python bridge suite** exercises persistent
multi-worker sessions, two launches before either wait, nonzero
worker exits, premature/duplicate operations, malformed and
oversized messages, stale request-ID protection, invalid
user-supplied cleanup handles, mock shutdown/descriptor-close
denial, and EOF during the lifecycle. The Bash regression also
uses a real `coproc` to launch three owned test workers, retains
opaque handles across read-equivalent phases and waits, and proves
that only a successful FINALIZE permits deletion of a
**synthetic** backing marker. Separate Bash tests reject
truncated/contradictory responses and preserve synthetic files
when a worker fails or the controller pipe disconnects.

**Both GitHub Actions workflows PASSED at one exact source revision**
`ec52145bd0543f80e7576236231184d32656f1e1`:

- Rootless teardown:
  https://github.com/k1moradi/swapz/actions/runs/37855300271
  — **23 bridge tests**, all four Bash bridge safety checks,
  34 pidfd IPC service tests and **10/10 full-suite repeats**,
  27 gated-pidfd supervisor tests and **3/3 repeats**,
  20 recall IPC adapter tests, 26 direct-dd allowlist tests,
  46 direct recall I/O tests, 23 swap-parser tests,
  16 pressure token tests and 10/10 repeats, 11 offline
  GC analyzer tests, plus both rootless teardown regressions.
- Combined NBD/teardown:
  https://github.com/k1moradi/swapz/actions/runs/37855300287
  — same gates plus static NBD syscall containment,
  compilation, **26/26 complete NBD selftests** and NBD/streaming
  teardown mocks.

An earlier pre-hardening code revision passed both CI gates;
an additional audit then caught and fixed stale request IDs on
malformed input and enforced socket-close verification before
positive FINALIZE. Both workflows were rerun after these changes
and passed at the exact revision above. Subsequent documentation
commits do not alter the tested code.

**Important limits:** bridge requests are intentionally restricted
to fixed `sleep`/`exit` test workers. The independently tested
direct-`dd` allowlist is not connected, and production
`buffer-recall.sh` still uses Bash job PIDs and background
reader functions; the PID reuse and descendant risks remain
unresolved. No real DM, loop, NBD, swap, systemd, kernel
module, physical device, fio, pressure/recall fixture or
benchmark operation was performed. See
`docs/recall-control-bridge.md` for the protocol and
production migration boundaries.

## 2026-10-08 — Pinned direct-dd actual-worker rootless qualification

**Tested executable-source revision:**
`4a89dc77752a28c53d62a6f81eec276e6438dfe0`.

Codex's opt-in descriptor-pinned role admission arrived in commits
`a0a1252a058f1c9f941ea178866a1a5060a988eb` and
`afffddadc99d8301a6e1494ae6e8237bf9becc29`.
The primary developer reviewed the service, role gate, pidfd launch boundary,
existing IPC adapter and Bash bridge; no production recall migration was made.
The direct-dd service mode remains disabled by the default CLI, and the
persistent Bash bridge still admits only fixed `sleep`/`exit` test workers.

An independent regression was added in
`tests/runtime/recall-dd-worker-integration-test.py` and gated in **both**
rootless CI workflows. Unlike the preceding fake-supervisor allowlist tests,
these **three rootless tests execute the actual pinned `/usr/bin/dd` binary**
through `GatedPidfdSupervisor`, with a temporary regular file standing in
for the test mapper. They confirm:

- All five roles (`writer`, `a`, `b`, `a2`, `b2`) use direct descriptor
  arguments, retain worker pidfds and yield exact readback of the specified
  nine source pages; the A/B concurrent phase launches both readers before
  waiting for either.
- Replacing `pages.bin` after writer admission cannot redirect the worker
  away from the retained source file descriptor.
- Replacing `read-a` after reader admission cannot redirect writes away
  from the retained output descriptor. The replacement pathname is untouched;
  this also shows why production comparisons must bind readback *identity*,
  not trust a mutable pathname after completion.
- Teardown uses supervisor-owned handles and never sends numeric-PID signals.

**Same-revision mandatory GitHub Actions: PASS**

- Rootless teardown:
  https://github.com/k1moradi/swapz/actions/runs/37858629277
- Combined NBD/teardown:
  https://github.com/k1moradi/swapz/actions/runs/37858629165

The combined log records the exact tested HEAD, the three new tests as
`ok`, the Bash bridge gate PASS, 10/10 complete IPC repeat runs and 25/25
additional NBD userspace selftests after the primary selftest. The new CI
workflow dependency ensures a change to the combined workflow also triggers
teardown qualification on the same source revision.

**Not established:** no real `/dev/mapper` descriptor, DM table identity
stability, kernel swapz behavior, live recall timings, swap pressure, process-
tree containment after supervisor death, real device teardown, or physical
performance was exercised. The opt-in role launcher and actual pidfd worker
lifecycle are still not integrated into the Bash bridge or production
`buffer-recall.sh`; do not authorize backing deletion on this evidence
alone. Subsequent documentation-only commits do not change the tested source.

## 2026-10-08 — Five-role pinned-readback and synthetic bridge qualification

**Fully qualified executable-source revision:**
`0592b47693ca95ca7ff3f07fc7f56a502bc83519`.

The independent primary-developer work adds:

- `recall-readback-identity.py`: attest exactly one fixed-role
  `read-a/read-b/read-a2/read-b2` 4 KiB file by a descriptor identity pinned
  *before* direct-worker launch. Reopen its retained O_WRONLY descriptor
  through `/proc/self/fd` for bounded readback, never through a mutable
  pathname; recheck directory, output, entry and size before/after reading.
  Compare only against an immutable in-memory expected page. Fail closed on
  replacement, symlink, hardlink, unexpected size, poison, descriptor or
  reference error. Borrowed descriptor ownership stays with the fixture.
- `RecallRoleIPCAdapter`: explicitly constructed, five-role-only client
  path requiring all five role launches, worker wait/reap attestations and
  successful identity-bound reader checks before `STOP_ALL`. Both concurrent
  readers must launch before either wait, and the staged writer must remain
  outstanding until all four reader checks finish. Preserve all original
  opaque-handle, stop report, shutdown and service-exit checks.
- `RootlessRoleBridge`: explicit trusted-injection-only class; the default
  Bash bridge constructor and normal service CLI still reject role requests.
  Role JSON accepts only an opaque fixed role, not arbitrary argv, paths,
  executable descriptors, mapper names or PIDs. Any exception permanently
  closes the injected library bridge to later cleanup authorization.
- `recall-role-service-integration-test.py`: actual AF_UNIX service/client
  wire protocol through Codex's descriptor-pinned role gate, with an injected
  non-forking fake supervisor and ordinary synthetic files. It exercises
  admission, identity capture, service launch/wait/stop/shutdown response
  handling and output replacement.
- `recall-role-bridge-fixture.py` and `recall-role-bridge-regression.sh`:
  genuine Bash coprocess with a permanently synthetic-only client, checking
  five-role handle continuity, failure and disconnect preservation.

**Both mandatory rootless GitHub workflows PASS at that exact code revision:**

- Teardown: https://github.com/k1moradi/swapz/actions/runs/37860393441
- Combined: https://github.com/k1moradi/swapz/actions/runs/37860393481

Combined logs show the 16-test rootless five-role adapter/bridge suite,
3-test true-service-wire/false-worker suite, 10 pinned readback identity
tests, the three Bash role-coprocess PASS markers, the prior three
real-pinned-GNU-`dd` tests, the existing Bash-to-pidfd bridge safety gate,
10/10 repeated IPC service suites, 25/25 additional NBD selftests
(26 including the primary selftest), and all remaining mandatory rootless
teardown/pressure/GC analysis gates passing.

**Critical scope boundary:** the new synthetic service-wire tests do
not create real `dd` processes or attest a real service process exit;
the genuine pinned-`dd` tests are independent rootless tests against
regular files. The normal service/bridge CLIs never opt in, the IPC wire
does not yet provide a trusted output descriptor or prelaunch inode
attestation across a separate service process, and production recall
remains unchanged. No supervisor-crash descendant containment, actual
DM mapping/table identity, live swap correctness, GC/read p99, batch
throughput calibration, or physical-media qualification was established.

No real device, DM/loop/NBD attach, swap/systemd, module load, pressure
fixture, production recall, fio benchmark, physical I/O or reboot was
performed. See `docs/recall-role-bridge.md` for the integration and
ownership boundary.

## 2026-10-08 — Real cross-process pidfd and pinned readback rootless qualification

**Tested executable-source revision:** `f1e07734b44ea88ebcb2f956773b92bd51cdc6ea`.

This milestone adds `recall-role-process-fixture.py` and
`recall-role-process-integration-test.py` and gates them in **both**
source-only CI workflows. These are not fake-supervisor or fake-process tests:
a real `Popen` service communicates over a private AF_UNIX stream, and its
real `GatedPidfdSupervisor` launches five direct workers with the existing
pinned-`dd` role policy and new seccomp/PDEATHSIG containment.

All I/O is against private regular files, never actual DM/loop/NBD devices
or swap. The fixture rejects root execution and non-regular synthetic
mappers. Its test executable is the installed `/usr/bin/dd` and is **not**
independently qualified as GNU coreutils.

**Exact readback binding:** a separate-service gate wrapper records the
trusted directory/output descriptor and inode identity *before* the worker
launch. Following confirmed zero-exit pidfd wait/reap, the same service
verifies each original pinned output against deterministic immutable 4096-B
reference data independent of the mutable source. The private `wait`
receipt binds role, opaque handle, verified result and exact expected-page
SHA-256. A rootless-only client validates receipt shape, digest and replay
before the existing base IPC validator; the role adapter also requires
receipt identity, all five waits and normal finalization rules. The default
service and bridge CLIs remain test-only and cannot opt into direct-`dd`
via remote role JSON.

**Mandatory same-executable-revision GitHub Actions: PASS**

- Teardown: https://github.com/k1moradi/swapz/actions/runs/37878408360
- Combined: https://github.com/k1moradi/swapz/actions/runs/37878408375

The combined job explicitly prints
`COMBINED_TESTED_HEAD=f1e07734b44ea88ebcb2f956773b92bd51cdc6ea`,
`Ran 7 tests` for the new genuine cross-process integration, the three
earlier real-pinned-`dd` tests, 10/10 repeated pidfd IPC suites,
`ROLE_BRIDGE_BASH_FIVE_ROLES: PASS` for the existing **synthetic-only**
Bash fixture, and `COMBINED_NBD_STRESS 25/25: PASS` after the initial
NBD selftest. All remaining rootless safety gates passed.

Adversarial process tests covered output-path substitution, source mutation,
premature writer/concurrent reader waits, abrupt service SIGKILL delivered
through a test-owned service pidfd, and controller-channel EOF. None of
those outcomes authorized synthetic backing cleanup. A fully successful
session verified all four reader pages, waited/reaped the staged writer,
confirmed all five handle receipts, completed stop/reap and service-process
exit, closed the control channel and removed *only* a synthetic marker.

Initial CI at `c72492f62557e2f972aade3a5a55568ed3bd18c0` intentionally
remains visible as **FAILED**, exposing a test-only mapper name outside the
existing `swapz-v22-recall-*` allowlist. The sole code correction was the
synthetic mapper name, in `f1e07734...`. Do not cite earlier failed
workflow runs as passing.

**Limits:** This does not authenticate GNU package provenance, bind a real
DM UUID/table lifecycle, guarantee kernel BIO drain after worker kill,
eliminate a same-UID in-place inode mutation after comparison, migrate
production `buffer-recall.sh`, run a real Bash bridge against device I/O,
or measure staged swap performance. No actual DM/loop/NBD attachment,
swap/module/pressure fixture, fio/device operation or benchmark was run.
See `docs/recall-role-process-rootless.md` and
`docs/v22-virtual-benchmark-qualification.md`. The next stage must
combine Codex's trusted executable/mapper policy and independently
reviewed I/O-drain evidence before operator-authorized virtual tests.

## 2026-10-09 — Offline V2.2 lower-device drain/p99 plateau qualification

**Tested executable-source revision:**
`bca327fd11d841870715171693faec2abc054838`.

A standalone strict, rootless JSONL observation analyzer was added at
`tests/runtime/v22-drain-plateau-analyze.py`, with 15 adversarial
selftests at `tests/runtime/v22-drain-plateau-analyze-test.py`. It
**does not execute any benchmark or device I/O**.

This corrects a reporting/evidence blind spot without modifying or
running the production benchmark: the existing
`streaming-benchmark.sh` field `drained_write_mib_s` is actually
logical fio `write.io_bytes` divided by an elapsed flush-inclusive
window, **not** independently observed lower-device drained bytes.
The analyzer instead computes throughput from independently supplied
lower-device 512-byte sector counter deltas over a positive monotonic
window. Observation provenance, quiescence, source isolation and
counter identity remain assertions that a separately approved collector
and operator must independently substantiate.

Validation enforces a complete 4..1024 KiB batched sweep, >=3 independent
repeats per point, >=10,000 swap-in read samples per run, <=10%
repeat-to-repeat drain spread, saturation at all final 256/512/1024 KiB
points within 97% of the series maximum median drain, and a candidate
read-p99 no more than 10% above the best worst-repeat p99 across eligible
plateau points. Failed correctness, drain, flush or worker finalization
flags are rejected outright, as are unknown schema fields, duplicate
run IDs or JSON keys, malformed counters, missing batches and unstable
data. The immediate 4 KiB baseline alone cannot assert saturation;
missing evidence reports `PLATEAU NOT REACHED`. Backend, profile,
strategy, code revision and evidence class are not pooled.

Synthetic observation data may produce an *illustrative candidate only*;
it never results in a provisional measured selection. `kernel` or
`physical` observations remain explicitly self-reported and may
produce only a provisional suggestion pending independent review.
No real performance winner can be inferred from these selftests.

**Both same-executable-revision source-only GitHub workflows: PASS**

- Teardown: https://github.com/k1moradi/swapz/actions/runs/37907017405
- Combined: https://github.com/k1moradi/swapz/actions/runs/37907017408

The combined run explicitly records
`COMBINED_TESTED_HEAD=bca327fd11d841870715171693faec2abc054838`,
`Ran 15 tests` for the new analyzer, 10/10 repeated pidfd IPC service
regressions and 25/25 additional userspace NBD selftests, alongside
existing rootless safety gates.

An intermediate run failed because of a mismatched quote in a new
invalid-JSON test literal; another caught an exact mismatch between
test-expected provenance wording and the report. Both issues were fixed
and the full suite rerun at the exact passing revision above.

No real dmsetup, loop, NBD attachment, swap, module load, pressure
fixture, fio/device benchmark, physical storage I/O or reboot occurred.
The actual V2.2 winning strategy and batch remain **UNDETERMINED**.
See `docs/v22-drain-plateau-offline.md` and
`docs/v22-virtual-benchmark-qualification.md`.

## 2026-10-09 — No false V2.2 streaming benchmark winner from one-run data

**Fully qualified executable-source revision:**
`ecd06d89b8c5f85bf67c6ec07b232625cce079ec`.

`tests/runtime/streaming-benchmark.sh` previously reported
`drained_write_mib_s = fio.logical_write_bytes / elapsed_flush_inclusive_s`
and nominated `first_97pct` and `latency_guarded` winners from
just one run for each batch. Neither constituted independently verified
physical drain or a repeatable saturation plateau. This milestone fixes
the *reporting path*, not the live benchmark setup:

- Sample the timed workload/flush window using
  `time.monotonic_ns()`, never wall-clock `date` time.
- Preserve separate, explicitly named `logical_flush_window_mib_s`
  (logical fio bytes per interval) and `lower_counter_window_mib_s`
  (lower sysfs 512-byte sector delta per interval). A lower device can
  have other clients, and neither this rate nor an upper flush by itself
  proves independent I/O quiescence or isolated completed physical bytes.
- Reject nonpositive elapsed time or decreasing/malformed lower counters
  before emitting a data row.
- Record actual fio `read_count` (`total_ios`) to expose too-short p99
  windows; retain lower I/O counts, upper bandwidth, latency and status.
- Remove the misleading `drained_write_mib_s` output field and
  remove the one-run `best_drain`/`first_97pct`/
  `latency_guarded` nomination entirely.
- Add `streaming-benchmark-report.py` as a standalone read-only
  JSONL report/check module. It verifies the numerator and denominator
  of both diagnostic rates against the recorded counters/times and
  rejects invalid status, missing samples, duplicate strategies/batches,
  backend mismatches, malformed/inconsistent data and impossible p99.
  The report always states `NO QUALIFIED WINNER` and
  `PLATEAU NOT REACHED`.
- Add `streaming-benchmark-report-test.py` (14 rootless tests), which
  uses only fabricated regular-file JSON, including running the real
  shell script's embedded fio/counter formatter in isolation to check
  distinct 8 vs 1 MiB/s diagnostic calculations. It explicitly does
  **not** source or execute the device benchmark shell script.

**Same executable-source GitHub Actions revision, both PASS:**

- Rootless teardown safety:
  https://github.com/k1moradi/swapz/actions/runs/37909068184
- Rootless combined source qualification:
  https://github.com/k1moradi/swapz/actions/runs/37909068343

The combined job logs identify
`COMBINED_TESTED_HEAD=ecd06d89b8c5f85bf67c6ec07b232625cce079ec`,
`Ran 14 tests` for the new reporting regression, 10/10 repeated
pidfd IPC suites, and 25/25 repeated userspace NBD protocol selftests.
All other existing mandatory rootless gates passed.

Earlier unqualified test revisions encountered a malformed quote
inside a fabricated invalid-JSON test literal; the final exact-source
run above recompiled and passed both workflows. No false-positive
live benchmark result was accepted.

**Not established:** independent GNU `dd` and DM lifecycle trust,
actual kernel physical drain, controlled backend isolation,
10,000+ reads/run, repeated nine-size saturation, read-p99
confidence, live production recall migration, or any V2.2 strategy/
batch winner. See `docs/streaming-benchmark-reporting.md` and
`docs/v22-drain-plateau-offline.md`.

No real DM, loop, NBD attach, swap, kernel module, live pressure
fixture, fio benchmark, device write or reboot was performed.

## 2026-10-09 — Synthetic DM drain orchestration and NBD PID-safety hold

**Exact tested executable-source revision:**
`4843e385e54a3389ab9156bc1ad08509affdd00c`.

Codex's existing `DMIODrainPolicy` remains unchanged. Both mandatory
CI workflows now explicitly run its eight policy regressions and 15
new rootless synthetic-orchestrator tests.

The new `RootlessMockDrainSession` drives the exact ordered evidence
contract from admission closure, five-role worker-handle inventory
and simulated swapoff through ordinary mock DM suspension,
descriptor/holder/open checks, upper-to-lower removal, verified mock
absence, loop dependency checks and simulated detach. It accepts
only an explicitly synthetic fixture state provider. A synthetic
backing marker is deleted **only after** successful state-machine
authorization and a second same-inode/private-marker identity check.
A failure at any of the 15 stages or in a separately tested inventory,
swapoff, noflush, close, open count, table identity, holder, removal,
loop or marker check permanently blocks that test session and preserves
the marker. This is **mocked logic**, not authenticated kernel evidence,
real Device Mapper suspend, real I/O drain or physical durability.

The existing streaming NBD benchmark's former `NBD_PID=$!` and
numeric `kill -0`/`kill -TERM` shutdown were **unsafe across PID
reuse**. Until an independently qualified exact-child/pidfd controller
exists, the streaming benchmark now rejects `SWAPZ_BENCH_BACKEND=nbd`
**before any allocation or worker/device launch**. Its legacy
`setup_nbd` function is an explicit refusal, and the separate
teardown helper cannot signal any numeric NBD PID; it returns failure,
preserving the backing session and diagnostics. This intentionally
disables the *live NBD benchmark mode*, not the rootless userspace NBD
protocol selftests. A distinct mocked NBD teardown regression now
requires no PID signals even after a successful mock DM removal.

**Both exact-revision rootless GitHub Actions: PASS**

- Rootless teardown safety:
  https://github.com/k1moradi/swapz/actions/runs/37910706506
- Rootless combined source qualification:
  https://github.com/k1moradi/swapz/actions/runs/37910706553

Combined log:
`COMBINED_TESTED_HEAD=4843e385e54a3389ab9156bc1ad08509affdd00c`,
`Ran 8 tests` for Codex's original drain model,
`Ran 15 tests` for the new rootless orchestrator,
10/10 repeated pidfd IPC regressions,
25/25 userspace NBD selftest repetitions, and
`unqualified NBD preserves backing without numeric PID signaling: PASS`.
The separately triggered NBD source-only suite also passed at
`2425700c4b8ebea63f658bd92b80e9d36c9bb201`, which already
included the changed NBD shutdown logic and its updated mock regression:
https://github.com/k1moradi/swapz/actions/runs/37910604753.
A preceding NBD workflow failed because the prior mocked teardown
expected an unsafe numeric-PID SIGTERM; its expectation was
deliberately replaced with the new fail-closed preservation contract.

**Unresolved:** actual kernel DM drain/loop detach, independently
anchored GNU coreutils trust, exclusive privileged mapper ownership,
a pidfd-owned NBD service/controller suitable for restoring the
NBD benchmark, production Bash recall migration and any real
physical-drain/read-p99 strategy/batch selection. NBD benchmark mode
must not be re-enabled by removing the guard without reviewing and
qualifying its complete process/cleanup lifecycle.

No real DM, loop, NBD attachment, swap, module operation, pressure
fixture, fio/device benchmark, physical I/O or reboot was performed.
See `docs/recall-io-drain-mock-integration.md`.

## 2026-10-09 — Real pidfd-owned synthetic NBD-like server process

**Tested executable-source revision:**
`3a039d7207c301f8b12a7aac4bd98bb8bc51a51c`.

A dedicated **test-only** exact-child service controller was added at
`tests/runtime/nbd-pidfd-owned-session.py`, with a single fixed
rootless mock child, `nbd-pidfd-owned-mock-child.py`.
Unlike the earlier static preservation guards, the new tests actually
start a separate non-root Python process, obtain a retained pidfd,
exchange a nonce-bound exact `SOCK_SEQPACKET` READY message,
deliver SIGTERM through `signal.pidfd_send_signal`, and verify the
exact owning `Popen.wait()` exit code. No reusable-PID signaling
fallback is provided. An abnormal shutdown escalates through that
same retained pidfd to SIGKILL and requires an owned reap.

**19 rootless adversarial tests** exercise a zero-exit stop, early
server exit, wrong/missing readiness, start timeout, ignored SIGTERM,
nonzero exit, spontaneous post-READY exit, failed pidfd signaling,
missing pidfd APIs, pidfd acquisition failure **after the owned child
has started** (resolved by closing the private channel and observing
the child's EOF-driven exit), illegal user-supplied mode/path,
non-private/symlinked fixture, repeated stop, premature context exit,
private diagnostic logs, and a static check prohibiting raw-PID
signal and device attachment code.

The controller's successful return explicitly labels
`exact_owned_process_reaped=True` and `zero_exit=True`, but
**`kernel_nbd_disconnected=False`, `dm_io_drained=False` and
`backing_cleanup_authorized=False`**. A parent-crash
descendant-containment guarantee, real NBD association/disconnect,
kernel request quiescence, and exclusive device identity are not
established. The live `SWAPZ_BENCH_BACKEND=nbd` gate remains
disabled, as does its numeric-PID shutdown path.

**All three exact-revision GitHub source-only workflows passed:**

- Rootless NBD safety:
  https://github.com/k1moradi/swapz/actions/runs/37913643602
- Rootless teardown safety:
  https://github.com/k1moradi/swapz/actions/runs/37913643708
- Rootless combined source qualification:
  https://github.com/k1moradi/swapz/actions/runs/37913643598

The combined job identifies
`COMBINED_TESTED_HEAD=3a039d7207c301f8b12a7aac4bd98bb8bc51a51c`,
shows `Ran 19 tests` for the new suite with actual `ok` results,
`PIDFD_IPC_REPEAT 10/10: PASS`,
`PRESSURE_TOKEN_REPEAT 10/10: PASS` and
`COMBINED_NBD_STRESS 25/25: PASS`.
An initial rootless test revision rejected `PosixPath` instances
using an incorrect exact class check; the check was corrected before
the fully passing same-source CI. There are no skipped tests in
the validated 19-case NBD mock result.

No real NBD attachment, DM/loop command, swap, kernel-module
operation, fio/device benchmark, actual block I/O or physical-device
operation occurred. See `docs/nbd-pidfd-owned-rootless.md`.

## 2026-10-09 — Main-developer Codex review and synthetic NBD crash containment

### Code review of Codex's trusted GNU + mapper owner commit

Primary developer reviewed `d2240b06e8a8fc5649d407d0c0344308896196e0`,
the diff's three owner-assigned files, and its exact-revision CI.
Full independent findings are in
`docs/codex-trust-bootstrap-review-2026-10-09.md`.

- **HIGH integration scope:** `MapperLifecycleOwner.cleanup_allowed`
  means the *one mapper lifecycle* has released. It does not attest a
  full DM stack drain, lower dependencies, or backing-file safety.
  `finalize_teardown()` also requires truthful externally supplied
  worker-reap and descriptor-close evidence, not arbitrary IPC booleans.
- **HIGH production blockers:** no independently authenticated actual
  static GNU `dd` source/build and trust provision, no verified
  GNU-under-seccomp execution and no privileged enforcement of
  exclusive DM table authority. Its cooperative lock is not such an
  authority.
- **MEDIUM deployment assumption:** pinned `/usr/bin/openssl` is
  dynamically linked; its interpreter/libraries/providers depend on
  a separately trusted host OS closure. Codex documented that fact.
- **Review disposition:** source-only contract is stronger and
  rootless policy tests passed; **not** production or mapper admission
  approval. Codex retains ownership of its GNU bootstrap files.

### Rootless synthetic NBD parent-crash and descendant safety

**Exact same executable-source revision tested in all three workflows:**
`14d1b9ae7b9a40906835b52d761640e58500e02e`.

The fixed synthetic NBD-like child now arms
`PR_SET_PDEATHSIG=SIGKILL` and immediately compares its expected
parent PID *only as identity evidence*, before reporting readiness.
The parent/child have separate private readiness/control channels;
control EOF normally terminates the mock. Linux-specific seccomp BPF
denies fork, vfork, clone, clone3, execve and execveat for the
recognized x86-64/AArch64 syscall ABIs and fails closed if filter
installation or architecture validation fails.

The separate fixed owner-crash fixture sends the child's retained
pidfd over AF_UNIX `SCM_RIGHTS` to an independent rootless observer,
then deliberately `os._exit`s before READY, immediately after READY,
or while idle. The observer polls **the exact pidfd** for child exit,
including a fixed mock variant that ignores channel EOF: this tests
kernel parent-death behavior independently of channel closure.
Observer exit proof is **not** a `wait()`/reap of the orphaned child.
Other tests inject PDEATHSIG registration refusal, fork/exec
attempts (both return EPERM), SIGTERM ignore, both failed pidfd
signal attempts, and failed bounded reap. The latter keeps the
stable pidfd for a later pidfd-only retry rather than losing process
identity. No numeric-PID signaling rescue path is permitted.

**24 real, non-skipped rootless process tests PASS** in:
- NBD source safety:
  https://github.com/k1moradi/swapz/actions/runs/37916615965
- Rootless teardown safety:
  https://github.com/k1moradi/swapz/actions/runs/37916615903
- Rootless combined qualification:
  https://github.com/k1moradi/swapz/actions/runs/37916615659

Combined job log identifies
`COMBINED_TESTED_HEAD=14d1b9ae7b9a40906835b52d761640e58500e02e`,
`Ran 24 tests`, `PIDFD_IPC_REPEAT 10/10: PASS`,
`PRESSURE_TOKEN_REPEAT 10/10: PASS` and
`COMBINED_NBD_STRESS 25/25: PASS`. No skipped child tests or
`ResourceWarning` appeared in the final NBD suite.

**Do not infer production NBD safety:** this is a fixed, already
executing synthetic Python child and a restricted test-only owner,
not the actual size-aware NBD server or its kernel session. No
trusted real server/argv/descendant closure, real kernel NBD
disconnect, actual DM I/O suspend/drain, loop dependency release
or backing cleanup authorization is established. Live
`SWAPZ_BENCH_BACKEND=nbd` remains explicitly disabled and the
V2.2 physical drain/read-p99 strategy winner remains UNDETERMINED.

No real DM, loop, NBD attach, swap, kernel module, fio/device
benchmark, physical storage IO or reboot was performed.

## 2026-10-09 — Offline plateau read-p99 internal-integrity gate

**Exact executable-source revision tested by BOTH mandatory workflows:**
`6f42f13fb00296e8c809eee79b4780fb67a0cfec`.

Main-developer audit found two performance-qualification risks in
`v22-drain-plateau-analyze.py`:

1. V1 allowed arbitrary self-reported `read_count >= 10000`
   and `read_p99_ns`; a JSONL series claiming kernel or physical
   evidence could produce an apparent provisional batch without
   any latency-distribution consistency checks.
2. The 97%-of-peak plateau predicate previously used six-decimal
   **display-rounded** MiB/s rather than original sector-derived
   rates, so a slightly subthreshold tail could be rounded into
   an eligible plateau.

The source-only fix adds strict `swapz-drain-observation-v2` with
a 1–256-bin, strictly ordered, **exact-value** latency/count
distribution (`read_latency_counts`). Counts must be positive
integers summing exactly to the bounded total
`10000 <= read_count <= 10000000`; latency values are positive,
strictly increasing, bounded nanoseconds. The tool recomputes
nearest-rank p99 at `ceil(0.99*N)` and refuses a mismatched
`read_p99_ns`. Common counter and duration integers are bounded.
Input v1 and v2 groups cannot pool; a v1 `kernel`/`physical`
claim now produces **neither candidate nor provisional selection**.
V1 `synthetic` fixtures remain explicitly illustrative.

For v2, even a `kernel` or `physical` observation with internally
consistent counted latencies can receive only
`PROVISIONAL - INDEPENDENT EVIDENCE REVIEW REQUIRED`.
Its labels, distributions, lower-device counters, timing and real
sample existence are **not authenticated**. A self-reported
histogram is not proof of actual swap-in reads, physical draining
or nonvolatile durability. Because the present exact-value format
permits only 256 distinct nanosecond latencies, it may be
inapplicable to real workloads with thousands of distinct samples;
do not silently round data or claim production collector readiness.

Threshold eligibility now uses **unrounded** sector-derived median
throughput; six-decimal rounding is strictly for output. The
new near-97%-boundary regression constructs a synthetic tail that
*displays* as 19.400000 MiB/s yet actually falls just below
97% of 20 MiB/s, and confirms the plateau is **rejected**.

**27 fully synthetic, rootless regressions PASSED at the same code
revision** (including wrong p99/count, invalid histogram types,
duplicate/non-monotone bins, fake excess samples, 64-bit counter
bounds, 99th-nearest-rank boundary, v1/v2 mixing and synthetic
no-winner gates). Exact GitHub Actions:

- Rootless teardown safety:
  https://github.com/k1moradi/swapz/actions/runs/37917836052
- Rootless combined source qualification:
  https://github.com/k1moradi/swapz/actions/runs/37917836051

Combined logs show
`COMBINED_TESTED_HEAD=6f42f13fb00296e8c809eee79b4780fb67a0cfec`,
`Ran 27 tests`, `PIDFD_IPC_REPEAT 10/10: PASS`,
`PRESSURE_TOKEN_REPEAT 10/10: PASS`, and
`COMBINED_NBD_STRESS 25/25: PASS`.

**Review note:** Some earlier in-progress combined runs failed in
the *existing* separate-process direct-dd recall integration with
`unconfirmed or duplicated recall role worker`; those failures
occurred outside this analyzer and should be separately investigated
for timing/admission races. The final exact-revision combined and
teardown runs both passed. Do not silently discard prior failures
when assessing broader system reliability.

No DM/loop/NBD attachment, swap, module, pressure fixture,
fio/device benchmark, real lower-device throughput measurement,
physical I/O or reboot was performed. The V2.2 batch/strategy
winner remains **UNDETERMINED**. See
`docs/v22-drain-plateau-offline.md`.

## 2026-10-09 — Primary-developer GNU review, recall ordering, and signed drain-model CI

**Exact executable revision tested successfully in both mandatory workflows:**
`f4c0be7eb7bc6d62c2d7485208018c527ee351af`.

- [Rootless combined](https://github.com/k1moradi/swapz/actions/runs/37941810631): **PASS**.
- [Rootless teardown](https://github.com/k1moradi/swapz/actions/runs/37941810576): **PASS**.

### Independent review of Codex's GNU 9.11 qualification

The main developer examined Codex's initial GNU source/build/worker
qualification code and records (commit
`9070372f5d8da9d78f0ffefda89e46fb2c3e9126`), rather than
treating a successful generic CI workflow as proof that a real
GNU binary was built or exercised. The original source inspector
executed an untrusted candidate's `--version` in an unrestricted
subprocess, and the original build-record verifier trusted two
self-reported, identical build outputs without hashing both.

Codex's follow-up commit
`d168378c28f755908b872e1c05583ccf5efc604d` now makes candidate
inspection passive, requires pinned descriptor/metadata/digest checks
and rehashes both exact build outputs before accepting a repeatability
claim. Main-developer code review confirms those checks are present;
the independently sourced GNU archive, second independent builder,
production signing credentials and real signed binary are **not**
reproduced or provisioned by the GitHub Actions unit tests. Real GNU
worker execution is supported by Codex's host record, not independently
rerun by this main-developer CI change. See
`docs/codex-gnu-9-11-review-2026-10-09.md`.

Codex's later `837b0059`/`c0e9b7d6` add a session-HMAC,
strictly ordered, identity-bound **model** for complete DM/loop drain
and backing-release evidence. The HMAC verifies reports using an
injected fixture-owner key, but no privileged evidence collector,
kernel DM suspend/drain, or actual backing cleanup was run.
The main developer independently wired its five model tests into
both mandatory rootless workflows, in addition to the original
eight DM policy and 15 synthetic orchestrator tests.

### Rootless five-role readback race: cause and containment

Earlier rootless combined/teardown runs had occasional safe denial
on short direct-dd role admission and missing WAIT receipts. Bounded
diagnostics now retain `service_status` and `service_error` rather
than reporting only an absent `worker` field. A later failing
positive test showed the exact error:
`pinned readback does not match trusted 4096-byte page`.

The test fixture had launched the small synthetic writer and begun
the first reader while the writer was still populating the regular
file. The pinning/attestation logic **correctly rejected** the
inconsistent read; it was not evidence of an incorrect page oracle.
The positive five-role test now waits with a bounded deadline until
the original pinned, privately owned synthetic mapper inode contains
the complete expected bytes **before** starting read roles. The
writer handle remains outstanding under the protocol and is waited
only after all four reader receipts are verified. There is no
unconditional sleep or retry of a denied session, and no admission
check was weakened. The corrupted-source negative test still expects
fail-closed denial.

Adversarial rootless tests also cover an unconfirmed launch, missing,
malformed and duplicated READY handles and failure to grant backing
cleanup after refusal. Each workflow repeats a full independent,
positive five-role session **six times**, failing immediately on a
single false admission. On the exact tested revision both
`RECALL_DIRECT_ROLE_REPEAT 6/6` steps passed.

### Exact source-only CI evidence

At `f4c0be7eb7bc6d62c2d7485208018c527ee351af` both workflows
explicitly ran the synthetic GNU provenance tests (7 cases), updated
build-record binding tests (10 cases), Codex authenticated
fixture-release-model tests (5 cases), original allowlist suite
(81 cases), and the existing NBD, pidfd, recall, pressure,
drain and offline plateau tests. The combined suite also reported
`COMBINED_NBD_STRESS 25/25: PASS`; all success applies to
**rootless source-only mocks/test-owned processes**.

A green 6/6 positive repeat does not prove the absence of all
scheduler races. Continue to preserve the bounded failure
diagnostics and fail closed rather than making READY optional.
No production GNU trust key/manifest, kernel-enforced mapper authority,
ordinary DM suspend, real kernel I/O drain, loop/NBD detach,
swap correctness under a real mapper, virtual benchmark or
physical-device benchmark was performed. V2.2 strategy and
batch size remain **UNDETERMINED**.

## 2026-10-09 — Adversarial fail-closed synthetic writer readiness

The main developer independently reviewed Codex's updated passive GNU
qualification, two-output build-record verification, mapper-only release
and session-HMAC drain policy (see
`docs/main-developer-fixture-owner-review-2026-10-09.md`).
No Codex-owned source was modified.

**Exact executable/source revision validated by BOTH mandatory workflows:**
`08f28d60648ce501ad6c86648db4f486f404994d`.

- [Combined CI PASS](https://github.com/k1moradi/swapz/actions/runs/37957362142).
- [Teardown CI PASS](https://github.com/k1moradi/swapz/actions/runs/37957362071).

Previously the positive rootless five-role recall fixture checked
regular-file writer bytes before starting readers, but an unsuccessful
writer-readiness assertion did not explicitly latch the bridge,
role adapter and IPC client as permanently denied. The main
developer hardened the fixture-only observation to require Linux
`O_NOFOLLOW`, a pinned regular-file descriptor and unchanged
dev/inode/owner/links/mode 0600/size; each read uses the pinned
descriptor and checks pathname identity and service process life.
A bounded deadline and strict exact-byte comparison precede
positive reader admission.

On any failed observation, the bridge, adapter and client
authorization are permanently denied, the control socket closes,
no additional reader roles can launch, and the synthetic backing
marker remains intact. The service's rootless EOF recovery may
reap its own worker, but that never grants cleanup. The writer
WAIT remains deferred until all four successful reader receipts
in the positive five-role protocol.

The expanded separate-process suite now includes **20 tests**;
10 newly added adversarial cases cover deterministic delayed
completion, missing bytes/timeout, truncation, correct-size wrong
page, replacement of pathname after pinning, symlink substitution
before pinning, read interruption, service EOF, invalid deadline,
and denial after a real writer was admitted but its data
observation was unconfirmed. All 20 passed in BOTH workflows;
each also ran **six independent positive five-role processes**
and reported `RECALL_DIRECT_ROLE_REPEAT 6/6: PASS`.

Other exact-revision proof from combined CI:
- GNU source/ELF policy **7 tests**, strict build-record policy
  **10 tests**; no live GNU source build or real-GNU execution.
- Direct dd allowlist **81 tests**.
- Authenticated fixture release **model: 5 tests**.
- Offline drain plateau **27 tests**.
- NBD rootless separate-process stress `25/25: PASS`.

Two earlier runs at `d1e232a1` failed a *new test's exact
error-wording assertion*; the data-integrity check had correctly
denied a substituted inode at its final verification stage.
`08f28d60` corrected only the assertion to accept either
identity-denial branch. Neither admission nor cleanup policy
was weakened.

This validates a **private regular-file test ordering barrier**,
not a kernel I/O fence, a completed writer protocol receipt,
nonvolatile persistence or physical DM/loop/NBD disappearance.
Production mapper admission and backing deletion remain blocked.
V2.2 strategy/batch winner remains **UNDETERMINED**.

## 2026-10-09 — Main-developer broker CI gate and independent security review

**Exact tested executable source:** `5c8acc47efe40e07baa8dd5fa8090dd453d5e965`.

- [Rootless combined](https://github.com/k1moradi/swapz/actions/runs/37995672935): **PASS**, exact `COMBINED_TESTED_HEAD` matches this SHA.
- [Rootless teardown](https://github.com/k1moradi/swapz/actions/runs/37995673013): **PASS**, same GitHub run head SHA.

The main developer inspected Codex's new `2f74389` broker/producer
implementation, the test bodies, typed mapper release-report changes and
the corresponding design reasoning. Full findings in
`docs/main-developer-broker-review-2026-10-09.md`.

Codex's 15-test `recall-fixture-owner-test.py` previously ran only
locally; both green generic workflows at `2f74389` **omitted** the new
suite. Both workflows now explicitly compile the broker and its test
and execute the **15 cases** with a 45-second timeout. Both then run
the complete 15-case suite in **three independent fresh Python
processes**, with 25-second timeouts and immediate failure on the
first unsuccessful repetition. Each workflow logged:
`FIXTURE_OWNER_BROKER_MODEL_ONLY: PASS`,
`FIXTURE_OWNER_BROKER_REPEAT 1/3: PASS`,
`2/3: PASS`, `3/3: PASS`.
The teardown push trigger includes
`recall-fixture-owner.py` and `recall-fixture-owner-test.py`;
the combined workflow covers `tests/runtime/**` already.

Both workflows also reported `RECALL_DIRECT_ROLE_REPEAT 6/6: PASS`;
the combined workflow additionally reported
`COMBINED_NBD_STRESS 25/25: PASS`. Existing GNU qualification,
allowlist, fake DM drain/loop, pressure, recall and offline
plateau gates remain intact.

**Two security blockers remain despite all green rootless CI:**

1. The broker's positive end-to-end test admits only
   `writer,a,b` but obtains
   `backing_release_authorized=True`. The fixed V2.2 recall
   protocol requires `writer,a,b,a2,b2`, with complete per-role
   outcomes and reader phase integrity. The producer currently
   derives its 'expected' handles from the already admitted set,
   not from the immutable fixture profile. Thus a truncated
   session can receive a positive model verdict.
2. The broker appends an opaque child handle only after its
   injected launcher returns. A launcher that starts a child and
   then fails before returning a valid handle can leave that
   child outside `_issued_handles` and the modeled best-effort
   stop inventory. Stable pidfd-owned child creation/handshake
   is not yet independently proved by this broker model.

These are assigned to Codex and remain NOT QUALIFIED by a
passing 15-case suite; the new main-developer workflow changes
do not alter Codex-owned policy. The model also uses fake peer
identity, a non-incrementing `_request_inflight` field, fake
kernel operation results and only one DM/loop layer, with no
NBD disconnect. Session HMAC and typed records prove modeled
sequencing, not actual kernel I/O drain or privileged authority.

No real DM, loop, NBD, swap, physical I/O, kernel module, device
benchmark or destructive backing cleanup occurred. Production
mapper admission and backing cleanup remain disabled. Independently
reproduced GNU static worker, production trust signing/provisioning,
true kernel drain and physical read-p99 qualification are still
outstanding. V2.2 batch and strategy winner **UNDETERMINED**.

## 2026-10-09 — Rootless workflow trigger/qualification drift regression

**Executable/source revision:**
`866002a13e74a8800a18c1cd3a3dc43fb9cf6292`.

- [Rootless teardown workflow](https://github.com/k1moradi/swapz/actions/runs/37996532817): **PASS**.
- [Rootless combined workflow](https://github.com/k1moradi/swapz/actions/runs/37996532854): **PASS**, `COMBINED_TESTED_HEAD` matches exact source SHA.

Independent main-developer safety audit found a concrete trigger omission:
`rootless-teardown.yml` executes `bash -n
tests/runtime/no-discard-livegc.sh`, yet the push path filter did not
include that file. A standalone modification to the checked shell
source could therefore skip this mandatory teardown workflow.

The teardown push filter now includes
`tests/runtime/no-discard-livegc.sh` and the new
`tests/runtime/rootless-workflow-contract-test.py` regression.
Both rootless workflows now explicitly run the six-test
source-only workflow contract under `timeout 20s`, using only
the Python standard library. Each CI log reports
`Ran 6 tests` and `ROOTLESS_WORKFLOW_CONTRACT: PASS`.

The guard checks that:
- Each runtime `.py`/`.sh` file mentioned in the teardown
  job is covered by its push trigger list (or an all-runtime
  wildcard). This includes syntax-only Bash sources.
- Both workflow YAML files and key runtime files trigger
  the relevant CI after modification.
- Mandatory GNU policy, fixture owner, authenticated release,
  I/O drain, recall role and offline plateau test scripts
  **actually execute as bounded Python tests**, not only appear
  in comments, compilation, or an unconditional PASS echo.
- The fixture-owner suite retains three independent, strict
  fail-fast repetitions; the five-role positive recall
  integration retains six.
- Both workflows have a read-only `GITHUB_TOKEN`.
- Adversarial selftests deliberately delete a push trigger,
  replace a broker/GNU/guard test command, or remove
  fail-fast behavior, and confirm the contract rejects it.

Both exact-source workflows also log
`RECALL_DIRECT_ROLE_REPEAT 6/6: PASS` and
`FIXTURE_OWNER_BROKER_REPEAT 3/3: PASS`.
The combined workflow additionally logs
`COMBINED_NBD_STRESS 25/25: PASS`.
These are **rootless/source-only tests**, with no real
DM/loop/NBD, swap, kernel drain or backing cleanup.
The contract is a static CI maintenance guard, not
an authenticated production security boundary.

Codex still owns fixing the new broker's incomplete five-role
positive release and unconfirmed-launch ownership gaps. The
main-developer workflow-contract task did not edit Codex's
owner, release, or GNU modules. Production direct-mapper
admission and backing deletion remain disabled, and the
V2.2 strategy/batch winner remains UNDETERMINED.

## 2026-10-09 — Three-workflow source-only safety contract, exact revision

**Final executable/source SHA:**
`00fbf74f155d537664b16252b92386636a34cc44`.

All three rootless workflows have passed at this identical commit:

- [Rootless teardown PASS](https://github.com/k1moradi/swapz/actions/runs/37996938227).
- [Rootless combined PASS](https://github.com/k1moradi/swapz/actions/runs/37996938277);
  log says `COMBINED_TESTED_HEAD=00fbf74f155d537664b16252b92386636a34cc44`.
- [Rootless NBD source safety PASS](https://github.com/k1moradi/swapz/actions/runs/37996938322).

The independently authored
`tests/runtime/rootless-workflow-contract-test.py` has **11
standard-library tests**, all passing in every workflow. It audits
both mandatory joint workflow scripts and the standalone NBD
workflow. Six original checks cover source push-trigger completeness,
mandatory bounded test execution, broker repeated tests, six
strict five-role recall repetitions, and negative mutations that
remove a trigger or a critical test command. Five extra checks
enforce the standalone NBD syscall-isolation gate, exact runtime
push-trigger coverage, 25 fail-fast NBD repetitions, pidfd-owned
mock test execution, and NBD workflow edits triggering teardown.
All tests are synthetic static workflow policy tests, not device
operations.

Previously, teardown ran a syntax check on
`no-discard-livegc.sh` without listing it in its push-path
triggers. This is now included. The teardown workflow now also
triggers when `.github/workflows/rootless-nbd.yml` changes;
otherwise shared NBD workflow contract changes would leave a
stale green teardown run. Both push and PR filters include the
cross-workflow dependency.

Standalone rootless NBD source safety now runs the same
workflow-contract suite before its AST-based syscall isolation,
NBD selftest and NBD mock pidfd lifecycle suite. Its own push/PR
filters include the workflow-contract source so edits cannot
silently bypass the standalone NBD gate.

Exactly verified log signals:
- Each workflow: `Ran 11 tests` and its own
  `ROOTLESS_*WORKFLOW_CONTRACT: PASS` message.
- Teardown and combined: `RECALL_DIRECT_ROLE_REPEAT 6/6: PASS`,
  `FIXTURE_OWNER_BROKER_REPEAT 3/3: PASS`.
- Combined: `COMBINED_NBD_STRESS 25/25: PASS`.
- Standalone NBD: `NBD rootless selftest repetition 25/25: PASS`
  and static syscall isolation PASS.

Several intermediate revisions failed **because the new contract
correctly refused an incomplete cross-workflow rollout** (one
workflow edited before its dependency). The *final identical*
three-workflow revision above is fully green. No admission/readback
verification was weakened to obtain a PASS.

No real DM, NBD/loop attachment, swap, kernel drain, physical I/O
or backing-file deletion was performed. Codex owns immutable five-role
broker completion, ambiguous child ownership, and real owner
authority/trust follow-ups. The main developer edited only workflows,
its own static regression suite, and docs. Production admission is
disabled and V2.2 strategy/batch winner remains **UNDETERMINED**.

## 2026-10-09 — Offline V2.2 evidence-bundle consistency and shared workflow dependency gate

**Exact executable/source SHA qualified by all three mandatory source-only workflows:**
`cf0752da282465bdf63b763c2b5621ce693b46a7`.

- [Rootless teardown PASS](https://github.com/k1moradi/swapz/actions/runs/37997610540).
- [Rootless combined PASS](https://github.com/k1moradi/swapz/actions/runs/37997610606),
  with `COMBINED_TESTED_HEAD` equal to the exact SHA above.
- [Standalone NBD source safety PASS](https://github.com/k1moradi/swapz/actions/runs/37997610596).

Independent main-developer work, without changing Codex-owned
modules, implemented
`tests/runtime/v22-evidence-bundle-check.py` and
`tests/runtime/v22-evidence-bundle-check-test.py`.
The checker reads exact, bounded original JSONL/manifest bytes
using no-symlink, regular-file descriptor pinning with metadata
consistency, strict duplicate-field-free JSON and LF-delimited
records. It reuses the existing strict V2.2 drain observation
validator and requires one coherent claimed 40-hex source
revision, collector, session, lower-device ID, backend, profile,
evidence class, and unique ordered run inventory. Original
whole-file and per-line SHA-256 bytes must exactly match the
separately provided manifest; mixed revisions and incomplete
or reordered inventories deny. Self-labeled kernel/physical
observations must use exact-latency V2 rather than self-reported
V1 p99.

**The checker makes no authentication claim**: the separately
provided manifest is untrusted and can be forged alongside
measurement bytes. The original JSONL has no authenticated
collector/session/device field. Its output always reports
`authenticated_collector=false`,
`independent_device_identity_proved=false`,
`kernel_drain_proved=false`,
`physical_selection_authorized=false` and
`backing_release_authorized=false`. Verified *consistency*
does not prove actual lower-device drain or real swap-in
latency. See `docs/v22-evidence-bundle-offline.md`.

Both combined and teardown workflow logs show
`Ran 20 tests` and
`V22_OFFLINE_BUNDLE_CONSISTENCY_ONLY: PASS`;
all observations/tests are synthetic, rootless and
source-only. The existing 20-case separate-process recall
suite and six independent positive five-role repetitions
remained intact; both logs report
`RECALL_DIRECT_ROLE_REPEAT 6/6: PASS` and
`FIXTURE_OWNER_BROKER_REPEAT 3/3: PASS`.
The combined workflow also reports
`COMBINED_NBD_STRESS 25/25: PASS`;
the standalone NBD workflow reports
`NBD rootless selftest repetition 25/25: PASS`.

The shared workflow contract now includes the offline bundle
suite as a mandatory executed bounded test in both joint
workflows. The standalone NBD workflow now triggers on edits
to either combined or teardown workflows because it executes
that same shared contract. A negative case asserts this
cross-workflow trigger dependency. All three workflows
reported **12/12 workflow-contract tests** and their
respective `ROOTLESS_*WORKFLOW_CONTRACT: PASS` messages.

Intermediate commits that updated only one related workflow
were rejected by the new contract, as intended. All three
runs on the exact SHA above succeeded; the test predicate
was not relaxed to obtain PASS.

No actual DM/loop/NBD attachment, swap, kernel operation,
physical I/O, device benchmark, nonvolatile drain or backing
deletion occurred. Independent GNU reproduction, trusted
signed source/per-device collection, privileged exclusive
mapper owner, authenticated kernel I/O drain and physical
p99 measurements remain unavailable. Production direct
mapper admission and backing cleanup stay disabled; V2.2
strategy and batch-size winner remain **UNDETERMINED**.


## 2026-10-09 — Independent five-role fixture broker policy review

The **exact executable source revision** is
`c166228e7c7a5aa3dce1a3bf7df8e236ca7be177`
([commit](https://github.com/k1moradi/swapz/commit/c166228e7c7a5aa3dce1a3bf7df8e236ca7be177)).
This source-only commit added
`tests/runtime/recall-broker-external-contract-test.py`
with five independent synthetic contract tests, made that suite mandatory in
both joint workflows, and extended the static workflow contract to enforce
the new bounded execution gate. It did not edit Codex-owned implementation.

All three rootless workflows completed successfully at this **same SHA**:

- [combined run 37999730905](https://github.com/k1moradi/swapz/actions/runs/37999730905)
- [teardown run 37999730780](https://github.com/k1moradi/swapz/actions/runs/37999730780)
- [standalone NBD run 37999730759](https://github.com/k1moradi/swapz/actions/runs/37999730759)

Job-step/log inspection confirms 5/5 independent broker tests passed in
both joint workflows; Codex's 31-test broker suite and all 3 fresh-process
broker repetitions passed; the six direct five-role repetitions passed;
the 12-test workflow contract passed; combined NBD selftest repetitions
reached 25/25, as did standalone NBD.

Independent audit: 
`docs/recall-broker-2eab914-independent-review.md`.
The formerly incomplete three-role admission policy now checks the exact
five-role sequence twice (broker and producer), and the ambiguous-child
launcher contract now requires best-effort cleanup of both unconfirmed and
registered worker handles. These are **rootless policy-model protections**
only. Actual crash-safe descendant containment and independently observed
kernel DM drain remain unqualified.

**Open concurrency issue**:
[GitHub #2](https://github.com/k1moradi/swapz/issues/2).
A concurrent request can latch DENIED while finalization holds the lock,
yet the finalizer lacks a post-collection denial check and may report
RELEASED/True. The exposed backing-authorization property stays false,
as the independent negative test confirms; this does not qualify safe
cancellation of modeled mapper/loop teardown or privileged operations.
Codex owns the implementation fix and stronger fail-stop regression.

This documentation change follows the executable source revision above;
do **not** treat this later documentation-only SHA as separately exercised
by all three workflows. No real DM, loop, NBD, swap, physical I/O,
backing deletion, or production privilege operation was performed.
V2.2 strategy and batch-size winner remain **UNDETERMINED**.


## 2026-10-09 — Source-only exact-revision CI evidence inventory

**Executable source commit:** `f9ee2ce35dfb84e78bd26ee2420b1588213af35f`
([commit](https://github.com/k1moradi/swapz/commit/f9ee2ce35dfb84e78bd26ee2420b1588213af35f)).

ChatGPT independently implemented:
- `tests/runtime/rootless-ci-evidence-inventory.py`: a standard-library-only,
  bounded regular-file/JSON validator for caller-supplied GitHub-shaped metadata
  of the exact three mandatory rootless workflows. It checks source SHA,
  run/job identity and attempt, ordered step metadata, selected safety step
  successes, and contradictory/missing/skipped/canceled outcomes.
- `tests/runtime/rootless-ci-evidence-inventory-test.py`: 33 rootless tests,
  including duplicate JSON keys, symlink and oversized-file rejection,
  mixed SHA/attempts, missing/failed mandatory tests, and fabricated
  step-name PASS claims.
- `docs/rootless-ci-evidence-inventory.md`: exact input schema, usage,
  limits and explicit negative authorization outcomes.
- Both joint workflows run the new suite under a 25-second timeout; the
  static workflow contract gates its execution and includes a new negative
  mutation test. The workflow contract increased from 12 to **13** tests.

**All three GitHub workflows passed against this exact executable SHA**:
- [Combined run 38001273677](https://github.com/k1moradi/swapz/actions/runs/38001273677): PASS.
- [Teardown run 38001273697](https://github.com/k1moradi/swapz/actions/runs/38001273697): PASS.
- [Standalone NBD run 38001273692](https://github.com/k1moradi/swapz/actions/runs/38001273692): PASS.

The two joint workflow logs recorded **33 inventory tests passed**
and **13 workflow-contract tests passed**, and their new inventory steps
have successful completed job-step metadata. The combined workflow also
recorded `COMBINED_TESTED_HEAD=f9ee2ce35dfb84e78bd26ee2420b1588213af35f`,
`RECALL_DIRECT_ROLE_REPEAT 6/6: PASS`,
`FIXTURE_OWNER_BROKER_REPEAT 3/3: PASS`, and
`COMBINED_NBD_STRESS 25/25: PASS`.

**Qualification boundary:** A positive inventory verdict establishes only
internally consistent *caller-supplied GitHub-shaped metadata*. It does
not authenticate the provider, runner, worker execution, physical device,
kernel drain, benchmark collector, or backing release. Repetition counts
remain unverified as independent execution attestations. All production
authorization flags are hard-coded false and the V2.2 strategy/batch
winner remains **UNDETERMINED**. No privileged kernel, loop, NBD, swap,
device-pressure, physical benchmark, or destructive cleanup operations
were run.

Codex concurrently owns the unresolved broker finalization-denial race
([issue #2](https://github.com/k1moradi/swapz/issues/2)); this contribution
does not edit that implementation. This validation-only commit comes after
the executable source commit, and should not be conflated with the exact
tested SHA recorded above.


## 2026-10-09 — Independent rootless recall-denial telemetry classification

**Exact executable commit:** `8857cad43e0df19056637280be370c4ab7cf1396`
([source-only feature](https://github.com/k1moradi/swapz/commit/8857cad43e0df19056637280be370c4ab7cf1396)).

ChatGPT implemented independently:
- `tests/runtime/recall-denial-telemetry.py`: a bounded source-only analyzer
  for JSONL **already-denied synthetic recall sessions**. Categorizes
  LAUNCH, READY, WAIT, READBACK, WRITER_READY, CHANNEL, PIDFD, FINALIZE,
  and STOP failures. Verifies exact asserted source revision, unique session
  identity, typed negative status/verdict, and SHA-256 of original bytes.
- `tests/runtime/recall-denial-telemetry-test.py`: **40** adversarial
  rootless tests for category precedence, malformed/fabricated receipts,
  duplicate fields/sessions, input framing/size, symlink and hardlink
  rejection, mixed revisions, zero exit-code denial, and stderr-only
  failed CLI behavior.
- `docs/recall-denial-telemetry-offline.md`: schema, invocation,
  and strict no-authorization/trust limitations.
- Both joint workflows execute the telemetry suite under a timeout;
  the static workflow contract includes a negative mutation gate,
  increasing from 13 to **14 tests**.

**Three GitHub workflows all green at this exact source revision:**

- [Combined 38002755119](https://github.com/k1moradi/swapz/actions/runs/38002755119)
- [Teardown 38002755147](https://github.com/k1moradi/swapz/actions/runs/38002755147)
- [Standalone NBD 38002755084](https://github.com/k1moradi/swapz/actions/runs/38002755084)

Both joint workflow logs record **40 telemetry tests** and
**14 workflow-contract tests** passed. The combined log includes
`COMBINED_TESTED_HEAD=8857cad43e0df19056637280be370c4ab7cf1396`,
`RECALL_DIRECT_ROLE_REPEAT 6/6: PASS`,
`FIXTURE_OWNER_BROKER_REPEAT 3/3: PASS`, and
`COMBINED_NBD_STRESS 25/25: PASS`.

This classifies **synthetically asserted** failures only. The analyzer
does not itself obtain or authenticate actual service logs, kernel
observations, device state, physical drain, or benchmark samples.
Its successful output hard-codes negative cleanup, backing release,
kernel drain, physical selection, and production qualification.
No real DM, loop, NBD, swap, module, physical I/O or destructive
cleanup occurred. V2.2 strategy/batch-size winner: **UNDETERMINED**.

A later Codex commit
`ae5f812e7647236ec91e8cae2102cceef0d6d9d5`
updated the broker's finalization/concurrent-denial implementation;
its joint workflow results must be reconciled **separately**. Do not
extend the three-way green telemetry revision claim to this newer
source without its own evidence. This validation-only commit changes
documentation, not the source revision tested above.


## 2026-10-09 — Pinned plateau input and monotonic denial external regression

**Source-only plateau input hardening:**
`bf95cbfce163a8c6fee3d0ac696fab85bcb9cd42`
([commit](https://github.com/k1moradi/swapz/commit/bf95cbfce163a8c6fee3d0ac696fab85bcb9cd42)).
The main developer eliminated a check/stat/open race in
`v22-drain-plateau-analyze.py` by reading from one bounded
retained no-symlink regular descriptor and checking before/after
metadata. Four adversarial tests covered symlink/hardlink/FIFO/UTF-8
denials; the original numerical qualification and p99 predicates
were unchanged. **31/31** plateau tests passed in the exact-source
[combined](https://github.com/k1moradi/swapz/actions/runs/38003239290)
and [teardown](https://github.com/k1moradi/swapz/actions/runs/38003239480)
workflows. This does not authenticate the collector or device and
does not solve the 256-distinct-raw-latency-value v2 schema limit.

**Independent broker fix verification:**
Codex's monotonic-denial source revision
`ae5f812e7647236ec91e8cae2102cceef0d6d9d5`
passed both joint workflows, followed by ChatGPT's independent stronger
test commit
`1d026ae61dbaa7717cdb64ee8fe744f60811c648`
([commit](https://github.com/k1moradi/swapz/commit/1d026ae61dbaa7717cdb64ee8fe744f60811c648)).
Its synthetic contention test now rejects a positive finalization
return and confirms no subsequent modeled swapoff, DM suspend/remove,
or loop detach after denial. Both
[combined run 38003419963](https://github.com/k1moradi/swapz/actions/runs/38003419963)
and
[teardown run 38003420160](https://github.com/k1moradi/swapz/actions/runs/38003420160)
passed on the **same exact executable revision**. Both logs include
**38 broker tests**, **5 independent broker tests**, **40 telemetry
tests**, **31 plateau tests**, and **14 workflow-contract tests**.
The combined workflow also completed 25/25 NBD selftest stress
repetitions. [Issue #2](https://github.com/k1moradi/swapz/issues/2)
is closed **for the rootless lifecycle model**. Production privileged
containment, authenticated kernel drain and real backing release remain
unqualified.

The latest standalone NBD source-only workflow pass belongs to the
earlier
`8857cad43e0df19056637280be370c4ab7cf1396`
revision; no standalone NBD workflow ran on this later independent
broker-contract revision. Do not mix different exact SHAs into a
three-way green claim. No live physical/kernel/device operation was
authorized or executed. V2.2 strategy and batch winner remain
**UNDETERMINED**. This subsequent validation documentation change
is documentation-only, not a new executable test revision.


## 2026-10-09 — Main-developer lossless V3 latency sidecar qualification

**Exact tested executable source:**
`ea18d3b6d81a5d307a855ce45228d3aabb07915f`
([code commit](https://github.com/k1moradi/swapz/commit/ea18d3b6d81a5d307a855ce45228d3aabb07915f)).
Initial prototype/test-fixture revisions were not green; only this
corrected exact source commit is recorded as the final gate.

Independent main-developer changes:
- The V2.2 plateau analyzer now accepts additive
  `swapz-drain-observation-v3` with strictly ordered
  exact-nanosecond RLE records, encoded as fixed 16-byte big-endian
  unsigned 64-bit latency/count pairs.
- Original sidecar bytes are hashed with SHA-256 during streaming,
  exact read_count is verified, and p99 is recomputed via the
  integer nearest-rank definition; neither coarsening nor discarded
  samples can manufacture a smaller p99.
- V3 sidecars are opened by basename relative to the same retained
  directory as the JSONL input and must be singly-linked, regular,
  no-symlink, uniquely bound, byte-aligned files. At most 512 MiB of
  sidecar bytes are processed per invocation, up to 10 million
  samples per run. V1/V2 interpretation and numerical plateau
  criteria remain unchanged.
- Added 39 targeted rootless V3 tests, a standalone format
  specification, mandatory 35-second test execution in each joint
  workflow, and a negative workflow-contract mutation check.
- The existing legacy V2.2 evidence-bundle schema verifies JSONL
  bytes only, not V3 sidecar bytes. It now explicitly rejects every
  V3 row instead of promoting an unverified sidecar hash into a
  positive manifest claim; two negative tests raise the bundle
  suite to 22 tests.

**Exact-revision GitHub Actions evidence:**
- [Combined 38026623024](https://github.com/k1moradi/swapz/actions/runs/38026623024): PASS.
- [Teardown 38026623030](https://github.com/k1moradi/swapz/actions/runs/38026623030): PASS.

Both job-step logs verified **39/39 V3 sidecar tests**,
**22/22 evidence-bundle tests**, **31/31 legacy plateau tests**,
and **15/15 workflow-contract tests**. The combined log records
`COMBINED_TESTED_HEAD=ea18d3b6d81a5d307a855ce45228d3aabb07915f`
and **25/25 NBD stress repetitions**. No standalone NBD run
for this exact commit was required or triggered.

**Rootless parser microbenchmark, not device performance:**
100,000 distinct sample timestamps encoded into 1,600,000 original
sidecar bytes were parsed with exact p99 in **0.2103 s** in combined
CI and **0.2850 s** in teardown CI. Both runs printed
**141,749 bytes** of peak Python-traced allocation for the parser
test. This is not full process RSS, and cannot be compared with
physical I/O throughput or swap-in latency.

**Qualification boundary:** The V3 sidecar digest binds only locally
supplied bytes. No trusted collector, signed source, independent
lower-device identity, kernel drain, genuine swap-in sampling,
production owner, actual backing deletion, live device, or physical
experiment was established or authorized. V2.2 strategy/batch winner:
**UNDETERMINED**. The later documentation-only commit must never
be substituted for the exact executable SHA verified above.


## 2026-10-09 — Source-only V3 sidecar-aware bundle integrity binding

**Exact executable commit:**
`98370f95e3cb6a1e708ecde242946c47c1b276e4`
([commit](https://github.com/k1moradi/swapz/commit/98370f95e3cb6a1e708ecde242946c47c1b276e4)).

The main developer independently implemented:
- `tests/runtime/v22-evidence-bundle-v3.py`:
  `swapz-v22-evidence-bundle-v2` with exact JSONL original-byte
  digest, per-run LF-inclusive SHA-256, and per-run V3 sidecar original-byte
  SHA-256, unique basename, validated size, exact read count and
  integer nearest-rank p99.
- Manifest assertions bind run/source revision, session, collector ID,
  lower-device ID, backend/profile and evidence label. The two metadata
  files and every sidecar must be read from the **same pinned directory**.
  Sidecars reuse the V3 analyzer's fail-closed 512-MiB global budget and
  10-million-sample per-run limits, with bounded streaming.
- `tests/runtime/v22-evidence-bundle-v3-test.py`: **43**
  synthetic rootless cases exercising positive full bundles, exact
  10,000-distinct-value p99, forged sidecar bytes/hash/length, mismatched
  run/session/collector/device assertions, duplicate sidecar or run
  identities, input traversal, symlink/hardlink/FIFO, schema mismatch,
  false p99/count, manifest tampering, and negative authorization.
- `docs/v22-evidence-bundle-v3.md` includes the exact
  schema and scope. Both joint workflows run the new 35-second bounded
  gate, while static contract tests now number 16. The old JSONL-only
  bundle verifier remains unchanged and denies V3 claims.

**All three workflows passed the exact source revision:**
- [combined run 38027940132](https://github.com/k1moradi/swapz/actions/runs/38027940132): PASS.
- [teardown run 38027940134](https://github.com/k1moradi/swapz/actions/runs/38027940134): PASS.
- [standalone NBD run 38027940133](https://github.com/k1moradi/swapz/actions/runs/38027940133): PASS.

Both joint logs recorded **43/43 V3 bundle cases, 39/39 V3 exact-latency
cases, 31/31 plateau cases, 22/22 legacy bundle policy cases,
and 16/16 static workflow-contract cases**. The combined log recorded
`COMBINED_TESTED_HEAD=98370f95e3cb6a1e708ecde242946c47c1b276e4`
and 25/25 standalone-process NBD stress repetitions.

**Limitations:** SHA-256 of user-supplied files protects only internal
byte consistency; a malicious author can replace both artifact and
digest. Manifest source, session, collector and device IDs are
**claims**. This does NOT establish a trusted signing key, real
kernel drain, swap-in sample source, production device identity,
privileged lifecycle owner, physical benchmark or cleanup authority.
All production flags are false, and the V2.2 strategy/batch winner is
**UNDETERMINED**. The later documentation-only commit must not be
represented as having its own separately tested executable SHA.
## 2026-10-09 — Kernel logical-range preflight and compiled C contract

**Exact executable source:** `af2b394e90805a7f9647c68cc58659ee83f8ff95`
([commit](https://github.com/k1moradi/swapz/commit/af2b394e90805a7f9647c68cc58659ee83f8ff95)).
The main developer audited `kernel/dm-swapz.c` and corrected two
failure modes: an out-of-range multi-page discard could invalidate
earlier live pages before returning -ERANGE, and a sector_t-derived
page index was narrowed to u32 before validation in read/write/discard.

Two pure C helpers now check the full-width index and whole discard
range *before* any staged-pack flush or logical-page mutation.
The test `tests/runtime/swapz-kernel-range-contract-test.py`
extracts and compiles **verbatim production helper bodies** into a
temporary unprivileged userspace C library, verifying limits with
ctypes. It also checks the source call order and key generation/GC/
flush guards and demonstrates rejection by two intentional mutants.

**Exact-revision GitHub Actions:**
- [Rootless combined 38028920840](https://github.com/k1moradi/swapz/actions/runs/38028920840): PASS; 30/30 kernel-range tests, 18/18
  workflow-contract tests and 25/25 NBD selftest stress repetitions.
- [Rootless teardown 38028920862](https://github.com/k1moradi/swapz/actions/runs/38028920862): PASS; 30/30 compiled/source
  guard tests and 18/18 workflow-contract tests.
- The standalone NBD gate passed at the preceding executable commit
  `53310d4defd04bcc2103d24f39c782727f2c99a3`
  ([run 38028809970](https://github.com/k1moradi/swapz/actions/runs/38028809970)),
  which has identical kernel source but predates a **test-only**
  Python syntax correction. Do not claim all three workflows passed
  the later exact SHA.

**Trust and execution boundaries:** Source-only C guard arithmetic
on a simulated 64-bit sector_t is not a whole-module build, real DM
discard correctness test, validated GC concurrency, swap-in latency
benchmark, authenticated kernel drain or backing-release permit.
Both protected local state files remain untouched; no real DM, loop,
NBD, swap, modules, block devices or destructive cleanup ran.
The V2.2 strategy/batch winner remains **UNDETERMINED**.
## 2026-10-09 — Independent source-level GC scratch alias fix

**Exact qualified executable SHA:**
`0d7e51a0273ec6124f7922567612cf0c2e00e05d`
([commit](https://github.com/k1moradi/swapz/commit/0d7e51a0273ec6124f7922567612cf0c2e00e05d)).

The main developer independently identified a nested GC/compaction alias:
the old `swapz_clean_segment` read a compressed victim into the shared
`io_buffer`, then decoded multiple live records. Relocating an earlier
record could submit a full batch and invoke `swapz_compact_fill_buffer`,
which overwrote `io_buffer` with an unrelated physical block before
the next live victim record was read. This was a source-level
data-integrity hazard, not an observed physical corruption event.

**Patch:** `kernel/dm-swapz.c` adds one preallocated `gc_source_buffer`
(4 KiB at the already-required PAGE_SIZE), changes the decoder to take an
explicit source pointer, uses it for both raw/compressed GC decode,
preserves the separate ordinary-read `io_buffer`, and frees the new
page during context cleanup. The change does not edit Codex's
supervisor, fixture owner, or containment files.

**Test design:** `tests/runtime/swapz-gc-source-contract-test.py` extracts
and executes the actual production C decoder and generation-current
predicate using a small synthetic container and test-only LZ4 stub.
It demonstrates that aliasing the source to overwritten scratch
invalidates the second record, whereas the dedicated snapshot
preserves its original bytes. The suite also checks synthetic
raw/corrupt/foreign source behavior, stale generations across a u32
wrap boundary, allocation/free contracts, GC source-call identity,
late-write failure retention, and victim-reclaim ordering.
This harness is *not* a full kernel LZ4 or GC pipeline test.

**Exact-source actions:**
- [Combined 38032711626](https://github.com/k1moradi/swapz/actions/runs/38032711626): PASS,
  exact head verified in job logs, 17/17 GC tests,
  30/30 kernel range tests, 19/19 workflow-contract tests,
  25/25 NBD stress repetitions, broker fresh-process 3/3.
- [Teardown 38032711514](https://github.com/k1moradi/swapz/actions/runs/38032711514): PASS,
  same exact head, 17/17 GC tests, 30/30 kernel-range tests,
  19/19 workflow-contract tests, broker fresh-process 3/3.
- Standalone NBD had passed on the preceding source commit
  `4c058c54f9ed93782c77a8d845c24cb115919556`
  ([run 38032323683](https://github.com/k1moradi/swapz/actions/runs/38032323683)),
  whose kernel source is identical but whose GC test had not yet
  been qualified. Do not claim a common three-workflow green SHA.

**Limitations:** The new suite runs extracted pure C and checks source
call order on synthetic data; it does not prove correctness under
real kernel dm-io, true LZ4, batch rollover, concurrent swap traffic,
actual I/O faults, process crash, privileged cleanup, or physical
measurement. Owner/collector authenticity and independent device
drain remain separate blockers. V2.2 strategy and batch winner:
**UNDETERMINED**. A subsequent documentation-only commit is not
a substitute for the exact executable SHA above.

## 2026-10-10 — GC compressed relocation buffer alias hardening

**Exact tested executable revision:** `f5379bc048b868be88210023229cdd133910c46c`,
[commit](https://github.com/k1moradi/swapz/commit/f5379bc048b868be88210023229cdd133910c46c).

A source audit identified a second conditional GC payload alias:
`swapz_clean_segment` used `context->compressed_buffer` for its
newly compressed relocation payload. Before `swapz_add_compressed_record`
copied that payload into the pack, it could reserve space or roll over an
existing pack, invoking write-batch compaction that also used
`context->compressed_buffer` as temporary record-copy scratch. The
result was a possible corrupted relocation record. This is a
source-level hazard, not measured live-device corruption.

The main developer changed `kernel/dm-swapz.c` to allocate
`gc_compressed_buffer` separately and use it only for GC compression.
Constructor and common unwind require and release the new page.
`tests/runtime/swapz-gc-compressed-contract-test.py` compiles the
**actual production compressed-pack staging C function**, supplies
rootless stand-ins for nested compaction, and compares protected
payloads with intentionally aliased payloads on both first-pack and
pack-rollover paths. The tests pin source/cleanup boundaries and verify
intentional source mutants fail. The harness is not real LZ4/dm-io.

**Same executable revision, three green GitHub Actions:**
- [Combined run 38033528668](https://github.com/k1moradi/swapz/actions/runs/38033528668):
  PASS, `COMBINED_TESTED_HEAD=f5379bc048b868be88210023229cdd133910c46c`,
  15/15 new GC compressed C tests, 17/17 previous GC source C tests,
  30/30 kernel range C tests, 20/20 workflow-contract tests,
  broker 3/3 fresh-process repeats, and NBD stress 25/25.
- [Teardown run 38033528694](https://github.com/k1moradi/swapz/actions/runs/38033528694):
  PASS, same SHA, 15/15 + 17/17 + 30/30 + 20/20 respective suites.
- [NBD source run 38033528707](https://github.com/k1moradi/swapz/actions/runs/38033528707):
  PASS on the same SHA.

**Safety boundary:** source-extracted C under mocked batch callbacks
is not a complete kernel module build, real GC, concurrent swap
traffic, physical-device audit, failure-injection test or production
cleanup approval. No privileged kernel/module, live swap/DM/loop/NBD
or destructive operations were performed. No Codex owner or broker
files were changed. The V2.2 strategy/batch winner is
**UNDETERMINED**.

## 2026-10-10 — Exact-C foreground generation / nested-GC transition qualification

**Executable SHA:** `ea41bae05b23d62128013864229ebf9a28658a46`.
[Rootless kernel source workflow run 38034762176](https://github.com/k1moradi/swapz/actions/runs/38034762176):
**PASS on exact SHA**, 21/21 new generation/GC transaction cases,
30/30 kernel-range guards, 17/17 GC source snapshot and 15/15 GC
compressed output cases.

`tests/runtime/swapz-generation-gc-transaction-test.py` extracts
five **verbatim production C functions**: logical-page range check,
stale stream-record check, uncommitted-generation check,
previous-generation commit and foreground write processing. It compiles
them with deterministic rootless stand-ins for nested GC relocation,
BIO copying and lower writes. Failure and rollback transitions,
`UINT32_MAX` rollover, committed-old-content preservation, and
out-of-bounds sector denial are executable in the userspace harness.
Five negative source mutants are rejected. The test does **not**
execute the actual kernel GC/reaper/dm-io/LZ4 pipeline.

The source audit did **not** demonstrate an independent second
generation-ordering defect requiring a production kernel change;
avoiding an unproven change to asynchronous BIO ownership is
intentional. Existing kernel production source at this commit remains
the separately verified GC scratch-buffer corrections.

A separate, non-overlapping Codex integration update to the same main
branch changed the recall supervisor worker result schema. The
combined and teardown workflows at
`9707bffaee190ec991bf1c99e62d72763f5322ff` were **red** in
`Rootless recall IPC adapter regression` due to
`ValueError: worker result has incorrect fields`; the unchanged adapter
still requires the previous strict shape. This is a cross-system
compatibility blocker, not a failure of the isolated kernel source
workflow. No combined/teardown green claim applies to the new
executable revision until Codex's adapter fix is independently green.

No live module, DM, loop, NBD, swap, physical media or privileged
cleanup was executed by the new kernel workflow. Authorized kernel
quiescence/collector provenance and the V2.2 strategy/batch winner
remain **UNDETERMINED**.

## 2026-10-10 — Exact-C async callback, watchdog and late-reap qualification

**Executable SHA:** `7ae05dedb66bdea71f1a39a2ced510c8a5f9628e`
([commit](https://github.com/k1moradi/swapz/commit/7ae05dedb66bdea71f1a39a2ced510c8a5f9628e)).

The main developer inspected the serialized kernel dm-io submission,
watchdog, async callback, completion reaper, staged mapping
publication, and teardown lifetime. A pending lower write **must not**
lose ownership of its stream memory simply because a watchdog has
reported a timeout. The source already keeps that buffer INFLIGHT,
fails outstanding upper BIOs once, retains previously acknowledged
resident staged data where authoritative, and waits on the actual
callback count before context destruction. No new reproducible
kernel defect was established, so production `kernel/dm-swapz.c`
was not modified in this increment.

New `tests/runtime/swapz-async-reap-contract-test.py` extracts and
compiles seven exact production C functions using deterministic
userspace stand-ins for Linux completion, queue, BIO and mapping
primitives. It tests nonblocking and blocking timeout, repeat
timeouts, late successful/error callbacks, timeout-boundary wins,
shutdown callback queue suppression, stale generation rejection,
acknowledged staged data retention and exactly-once upper BIO
completion. Deliberately invalid mutations of callback-ref draining,
submission error publication, premature buffer recycling, lost
BIO ownership and staged-data retention are rejected.

**All exact-SHA CI:**
- [Isolated kernel source 38035848146](https://github.com/k1moradi/swapz/actions/runs/38035848146):
  PASS, 22/22 new async, 21/21 generation,
  15/15 GC compressed, 17/17 GC source, 30/30 range.
- [Rootless combined 38035848163](https://github.com/k1moradi/swapz/actions/runs/38035848163):
  PASS, 22/22 async plus the four existing kernel contract
  suites, 22/22 workflow-contract tests, and 25/25 NBD stress.
- [Rootless teardown 38035848200](https://github.com/k1moradi/swapz/actions/runs/38035848200):
  PASS, same exact SHA and all new/previous kernel contracts
  plus 22/22 workflow-contract tests.

A later Codex commit `3e8dacf9213d45688e78f649bfcec14b4d7473f2`
changed only `tests/runtime/recall-fixture-owner-test.py` relative to
the tested async revision; it is not a substitute for the exact
executable SHA above.

**Limits:** The exact production C functions run against bounded
synthetic user-mode scheduling and mapping primitives. These tests
are not actual kernel workqueue/dm-io interleavings, module-build
results, physical device fault injection, swap performance,
kernel I/O quiescence or backing-release authorization. Never-
completing callbacks remain a fail-closed teardown/liveness risk,
not a license to free memory. No physical or privileged action
was performed. V2.2 strategy/batch winner **UNDETERMINED**.

## 2026-10-10 — Rootless exact-production-C FUA/PREFLUSH contract

**Exact executable source commit:**
`83d2e41d7d72e7dbedb3ad5860b0dc4359aac988`
([commit](https://github.com/k1moradi/swapz/commit/83d2e41d7d72e7dbedb3ad5860b0dc4359aac988)).

Reviewed `swapz_process_bio`, `swapz_process_flush`,
`swapz_stage_write_block`, `swapz_submit_stream_buffer`,
`swapz_finalize_stream_buffer`, `swapz_reap_inflight` and the
serialized I/O worker. Found no source-confirmed new kernel
durability defect. The production kernel file was left unchanged.

New `tests/runtime/swapz-flush-fua-contract-test.py` compiles
exact C flush/upper dispatch and physical-batch staging,
with bounded synthetic lower/device/BIO dependencies. There are
nine Python tests, including 20 executable C scenarios and six
negative source mutation tests: preflush-before-current-write;
zero-sector flush exclusion; batch and backing-flush errors;
mixed FUA and plain compressed payloads; early completion only
without FUA; raw/non-staged FUA; lower dm-io FUA flag propagation
pinned to production source.

**CI, one exact SHA:**
- [Isolated kernel 38039036487](https://github.com/k1moradi/swapz/actions/runs/38039036487):
  PASS, new 9/9 and prior 22/22 async, 21/21 generation,
  15/15 GC compression, 17/17 GC source, 30/30 range.
- [Combined 38039036567](https://github.com/k1moradi/swapz/actions/runs/38039036567):
  PASS, new FUA gate plus 23/23 workflow-contract tests, NBD
  stress 25/25.
- [Teardown 38039036488](https://github.com/k1moradi/swapz/actions/runs/38039036488):
  PASS with new gate and previous safety suites.
- [Standalone NBD 38039036489](https://github.com/k1moradi/swapz/actions/runs/38039036489):
  PASS.

**Limitations:** This is extracted production C in a synthetic,
rootless harness, not a live module or verified backing-media
persistence. A staged non-FUA upper success is explicitly RAM-only
until lower completion; lower FUA and preflush durability still
requires authorized real-device fault injection. No real swap, DM,
loop, NBD, module, pressure, physical-device manipulation,
reboot or cleanup occurred. See
`docs/v22-flush-fua-durability-audit.md`.
Strategy/batch winner: **UNDETERMINED**.
