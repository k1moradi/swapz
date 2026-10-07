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
