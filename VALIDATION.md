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
